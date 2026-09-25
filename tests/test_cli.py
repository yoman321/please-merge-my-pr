"""Gates for the CLI contract, I10 limit, I11, I14, and the reason fallback."""

from __future__ import annotations

import importlib.resources
import json
import math
import re
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import API, TESTS_DIR, assert_ran, guard, record_opens, run_cli
from fake_github import FakeGitHub

LINE = re.compile(r"^#(\d+) (.+)   \[score (\d+)\]$")
WATCH_LINE = re.compile(r"^\+ ([\w.-]+/[\w.-]+)#(\d+) (.+)   \[score (\d+)\]$")


def ranked_world() -> FakeGitHub:
    """Scores 29, 14, 14, 5 → ranks 1, 2, 2, 4."""
    now = datetime.now(UTC)
    fake = FakeGitHub(API)
    fake.add_queued(
        "acme/api", 412, now - timedelta(days=7), files=[("auth/session.py", 300, 80)]
    )
    fake.add_queued(
        "acme/api", 20, now - timedelta(days=7), files=[("src/a.py", 300, 80)]
    )
    fake.add_queued(
        "acme/web", 21, now - timedelta(days=7), files=[("src/a.py", 300, 80)]
    )
    fake.add_queued(
        "acme/web", 30, now - timedelta(hours=1), files=[("src/b.py", 10, 0)]
    )
    return fake


def keys_sorted(text: str) -> bool:
    ok = True

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        nonlocal ok
        keys = [k for k, _ in pairs]
        ok = ok and keys == sorted(keys)
        return dict(pairs)

    json.loads(text, object_pairs_hook=hook)
    return ok


def pr_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if LINE.match(line)]


# ---- I10 via the CLI ----------------------------------------------------


def test_shared_rank_limit_keeps_group(live: Mapping[str, Path]) -> None:
    fake = ranked_world()
    result = run_cli(["list", "--limit", "2"], transport=fake)
    assert_ran(result)
    assert pr_lines(result.out) == [
        "#412 touches auth · waiting 7d · 380 lines   [score 29]",
        "#20 waiting 7d · 380 lines   [score 14]",
        "#21 waiting 7d · 380 lines   [score 14]",
    ]
    assert "+1 more · please-merge-my-pr list --all" in result.out.splitlines()


# ---- CLI contract ------------------------------------------------------


def test_cli_contract(live: Mapping[str, Path]) -> None:
    fake = ranked_world()

    limited = run_cli(["list", "--limit", "2", "--json"], transport=fake)
    assert_ran(limited)
    assert keys_sorted(limited.out)
    data = json.loads(limited.out)
    assert set(data) == {"shown", "total", "could_not_check", "items"}
    assert (data["shown"], data["total"], data["could_not_check"]) == (3, 4, 0)
    for item in data["items"]:
        assert set(item) == {"rank", "repo", "number", "score", "reason"}
    assert [(i["rank"], i["repo"], i["number"], i["score"]) for i in data["items"]] == [
        (1, "acme/api", 412, 29),
        (2, "acme/api", 20, 14),
        (2, "acme/web", 21, 14),
    ]

    default = json.loads(run_cli(["list", "--json"], transport=fake).out)
    assert default["shown"] == 3  # default limit 3: ranks 1, 2, 2
    everything = json.loads(run_cli(["list", "--all", "--json"], transport=fake).out)
    assert (everything["shown"], everything["total"]) == (4, 4)
    assert [i["rank"] for i in everything["items"]] == [1, 2, 2, 4]

    why = run_cli(["why", "acme/api#412", "--json"], transport=fake)
    assert_ran(why)
    assert keys_sorted(why.out)
    detail = json.loads(why.out)
    assert set(detail) == {"repo", "number", "score", "exact", "rows"}
    assert (detail["repo"], detail["number"], detail["score"]) == ("acme/api", 412, 29)
    assert len(detail["rows"]) == 7
    assert abs(detail["exact"] - 28.8) < 1e-3

    for bad in ("0", "-1"):
        assert_ran(run_cli(["list", "--limit", bad], transport=fake), 2)

    twins = FakeGitHub(API)
    requested = datetime.now(UTC) - timedelta(days=1)
    twins.add_queued("acme/api", 7, requested, files=[("src/a.py", 1, 0)])
    twins.add_queued("acme/web", 7, requested, files=[("src/a.py", 1, 0)])
    ambiguous = run_cli(["why", "7"], transport=twins)
    assert_ran(ambiguous, 1)
    assert "acme/api#7" in ambiguous.out + ambiguous.err
    assert "acme/web#7" in ambiguous.out + ambiguous.err
    assert_ran(run_cli(["why", "acme/web#7"], transport=twins), 0)


def test_empty_reason_fallback_output(live: Mapping[str, Path]) -> None:
    fake = FakeGitHub(API)
    fake.add_queued(
        "acme/api", 5, datetime.now(UTC) + timedelta(days=1), files=[], rollup="FAILURE"
    )

    plain = run_cli(["list"], transport=fake)
    assert_ran(plain)
    assert pr_lines(plain.out) == ["#5 nothing notable   [score 0]"]

    data = run_cli(["list", "--json"], transport=fake)
    assert_ran(data)
    assert [
        (i["number"], i["reason"], i["score"]) for i in json.loads(data.out)["items"]
    ] == [(5, "nothing notable", 0)]


# ---- I14 ---------------------------------------------------------------


def demo_items() -> list[dict[str, Any]]:
    result = run_cli(["list", "--demo", "--all", "--json"])
    assert_ran(result)
    data = json.loads(result.out)
    assert data["shown"] == data["total"] == len(data["items"])
    return list(data["items"])


def test_demo_offline(isolated: Mapping[str, Path]) -> None:
    with guard(network=True, subprocess=True) as violations:
        items = demo_items()
        assert len(items) >= 2
        target = f"{items[0]['repo']}#{items[0]['number']}"

        listing = run_cli(["list", "--demo"])
        why = run_cli(["why", target, "--demo"])
        show = run_cli(["show", target, "--demo"])
        watch = run_cli(["watch", "--demo"])
    assert violations == []
    for result in (listing, why, show, watch):
        assert_ran(result)
    assert "summary: not enabled" in show.out.splitlines()
    watch_lines = [line for line in watch.out.splitlines() if line.startswith("+ ")]
    assert all(WATCH_LINE.match(line) for line in watch_lines), watch.out
    assert len(watch_lines) == len(items)


def test_demo_is_package_data(isolated: Mapping[str, Path], built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        assert "please_merge_my_pr/demo/demo.json" in wheel.namelist()
    resource = importlib.resources.files("please_merge_my_pr").joinpath(
        "demo/demo.json"
    )
    assert resource.is_file()
    json.loads(resource.read_text())

    with record_opens() as opened:
        assert_ran(run_cli(["list", "--demo"]))
    tests_dir = str(TESTS_DIR)
    assert [p for p in opened if p.startswith(tests_dir)] == []
    assert any(
        p.replace("\\", "/").endswith("please_merge_my_pr/demo/demo.json")
        for p in opened
    ), opened


# ---- I11 ---------------------------------------------------------------


def test_why_adds_up(isolated: Mapping[str, Path]) -> None:
    items = demo_items()
    assert len(items) >= 2
    for item in items:
        ref = f"{item['repo']}#{item['number']}"
        result = run_cli(["why", ref, "--demo", "--json"])
        assert_ran(result)
        detail = json.loads(result.out)
        exact = detail["exact"]
        assert len(detail["rows"]) == 7, ref
        assert abs(sum(r["points"] for r in detail["rows"]) - exact) < 1e-9, ref
        assert abs((100 - sum(r["off"] for r in detail["rows"])) - exact) < 1e-9, ref
        assert math.floor(exact + 0.5) == item["score"] == detail["score"], ref


@pytest.mark.parametrize("argv", [["list", "--limit", "0"], ["list", "--limit", "-1"]])
def test_cli_contract_bad_limit_demo(
    argv: list[str], isolated: Mapping[str, Path]
) -> None:
    assert_ran(run_cli([*argv, "--demo"]), 2)
