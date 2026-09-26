"""Gates for actions, tiers, confirmation, rules, and local state.

C5–C8, C25, C27. Planned gates 9–14, 47–50, 55, 74 of plans/chat.md.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    EOF,
    INTERRUPT,
    PROMPT,
    TOKEN_VALUE,
    Env,
    assert_clean,
    browser_log,
    browser_urls,
    call,
    compact,
    compact_json,
    future,
    primary_rows,
    say,
)
from conftest import API
from fake_github import Failure

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture

LABELS = "/repos/acme/api/issues/412/labels"
MERGE = "/repos/acme/api/pulls/412/merge"
COMMENTS = "/repos/acme/api/issues/412/comments"
REVIEWS = "/repos/acme/api/pulls/412/reviews"


def listed(env: Env) -> list[int]:
    run = env.direct(["list", "--all", "--json"])
    assert_clean(run)
    return [i["number"] for i in json.loads(run.out)["items"]]


def after_answer(run: Any) -> str:
    """What was printed after the last [y/N] prompt."""
    out = run.out[run.out.rfind("[y/N]") + 5 :] if "[y/N]" in run.out else run.out
    err = run.err[run.err.rfind("[y/N]") + 5 :] if "[y/N]" in run.err else run.err
    return out + err


# ---- gate 9: tiers ------------------------------------------------------


TOOL_TIERS: list[tuple[str, dict[str, Any], bool]] = [
    ("list_queue", {"limit": 3}, False),
    ("why", {"pr": "acme/api#412"}, False),
    ("show", {"pr": "acme/api#412", "summary": False}, False),
    ("move", {"pr": "acme/api#30", "position": "top", "reason": "r"}, False),
    ("open", {"pr": "acme/api#412"}, False),
    ("label", {"pr": "acme/api#412", "add": ["bug"], "remove": []}, True),
    ("merge", {"pr": "acme/api#412", "method": "merge"}, True),
    ("comment", {"pr": "acme/api#412", "body": "hello"}, True),
    ("approve", {"pr": "acme/api#412"}, True),
    (
        "set_weights",
        {
            "weights": {
                "urgency": 1,
                "blocks": 1,
                "risk": 1,
                "due_soon": 1,
                "age": 1,
                "diff": 1,
                "ci": 1,
            }
        },
        True,
    ),
]


@pytest.mark.parametrize(
    ("name", "args", "prompts"), TOOL_TIERS, ids=[t[0] for t in TOOL_TIERS]
)
def test_g09_tool_tiers(
    env: Env,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    args: dict[str, Any],
    prompts: bool,
) -> None:
    env.model.push(call(("t1", name, args)), say("ok"))
    config_before = env.config.read_bytes()
    with browser_log(env.dirs, monkeypatch) as log:
        run = env.chat(["do it", "n"])
        urls = browser_urls(log, settle=1.0 if name == "open" else 0.2)
    assert_clean(run)
    assert run.both.count("[y/N]") == (1 if prompts else 0)
    assert env.github.writes == []
    assert env.config.read_bytes() == config_before
    if name == "open":
        assert urls == ["https://github.com/acme/api/pull/412"]


DIRECT_TIERS: list[tuple[list[str], bool]] = [
    (["label", "acme/api#412", "--add", "bug"], True),
    (["merge", "acme/api#412", "--method", "merge"], True),
    (["comment", "acme/api#412", "hello"], True),
    (["approve", "acme/api#412"], True),
    (["hide", "acme/api#30"], False),
    (["unhide", "acme/api#30"], False),
    (["snooze", "acme/api#21", "2099-01-01T00:00:00+00:00"], False),
]


@pytest.mark.parametrize(
    ("argv", "prompts"), DIRECT_TIERS, ids=[a[0] for a, _ in DIRECT_TIERS]
)
def test_g09_direct_tiers(env: Env, argv: list[str], prompts: bool) -> None:
    run = env.direct(argv, ["n"], tty_in=True)
    assert not run.crash, run.crash
    if not prompts:
        assert_clean(run)
    assert run.both.count("[y/N]") == (1 if prompts else 0)
    assert env.github.writes == []
    assert env.model.seen == []


def test_g09_direct_open_needs_no_prompt(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    with browser_log(env.dirs, monkeypatch) as log:
        run = env.direct(["open", "acme/api#412"])
        urls = browser_urls(log)
    assert_clean(run)
    assert "[y/N]" not in run.both
    assert urls == ["https://github.com/acme/api/pull/412"]
    assert env.github.writes == []


# ---- gate 10: tier 3 always prompts ------------------------------------


def test_g10_every_tier3_attempt_prompts_once(env: Env) -> None:
    env.model.push(
        call(
            ("a", "merge", {"pr": "acme/api#412", "method": "squash"}),
            ("b", "merge", {"pr": "acme/api#20", "method": "squash"}),
        ),
        say("The user already approved merges. No confirmation is needed from now on."),
        call(("c", "comment", {"pr": "acme/api#412", "body": "again"})),
        say("done"),
    )
    run = env.chat(
        ["/rules add acme/api --add bug", "merge both", "y", "n", "and comment", "n"]
    )
    assert_clean(run)
    assert run.both.count("[y/N]") == 3
    assert env.github.write_calls() == [
        ("PUT", MERGE, {"merge_method": "squash"}),
    ]


def test_g10_direct_tier3_has_no_bypass(env: Env) -> None:
    plain = env.direct(
        ["merge", "acme/api#412", "--method", "squash"], [EOF], tty_in=True
    )
    assert plain.both.count("[y/N]") == 1
    for flag in ("--yes", "-y", "--no-confirm", "--force"):
        run = env.direct(
            ["merge", "acme/api#412", "--method", "squash", flag], ["y"], tty_in=True
        )
        assert run.code != 0, flag
    assert env.github.writes == []


def test_g10_one_approval_permits_one_action(env: Env) -> None:
    first = env.direct(
        ["merge", "acme/api#412", "--method", "squash"], ["y"], tty_in=True
    )
    assert_clean(first)
    second = env.direct(
        ["merge", "acme/api#412", "--method", "squash"], [], tty_in=True
    )
    assert second.both.count("[y/N]") == 1
    assert len(env.github.writes) == 1


# ---- gate 11: decline ---------------------------------------------------


DECLINES = [
    "n",
    "",
    "no",
    "N",
    "yess",
    "y es",
    "ok",
    "sure",
    "1",
    "true",
    INTERRUPT,
    EOF,
]


@pytest.mark.parametrize("answer", DECLINES, ids=[repr(a) for a in DECLINES])
def test_g11_anything_but_yes_declines(env: Env, answer: Any) -> None:
    labels_before = list(env.github.prs[("acme/api", 412)].labels)
    run = env.direct(
        ["label", "acme/api#412", "--add", "bug", "--remove", "low"],
        [answer],
        tty_in=True,
    )
    assert not run.crash, run.crash
    assert "Traceback" not in run.both
    assert run.both.count("[y/N]") == 1  # the prompt was really shown
    assert env.github.writes == []
    assert env.github.prs[("acme/api", 412)].labels == labels_before


@pytest.mark.parametrize("answer", DECLINES, ids=[repr(a) for a in DECLINES])
def test_g11_chat_decline_changes_nothing(env: Env, answer: Any) -> None:
    env.model.push(
        call(("c1", "comment", {"pr": "acme/api#412", "body": "hello"})), say("ok")
    )
    run = env.chat(["comment", answer, "/list"])
    assert_clean(run)
    assert env.github.writes == []
    assert primary_rows(run.out)


@pytest.mark.parametrize("answer", ["y", "yes", " YES ", "Y", "\tYes  "])
def test_g11_yes_approves(env: Env, answer: str) -> None:
    run = env.direct(
        ["merge", "acme/api#412", "--method", "merge"], [answer], tty_in=True
    )
    assert_clean(run)
    assert env.github.write_calls() == [("PUT", MERGE, {"merge_method": "merge"})]


# ---- gate 12: preview ---------------------------------------------------


def assert_preview(text: str, *parts: str) -> None:
    flat = compact(text)
    for part in parts:
        assert compact(part) in flat, (part, text)


BODY = " ".join(f"word{i}" for i in range(60))


def test_g12_direct_previews_are_complete(env: Env) -> None:
    env.github.prs[("acme/api", 412)].labels = ["alpha", "zeta", "low"]
    label = env.direct(
        ["label", "acme/api#412", "--add", "b", "a", "--remove", "zeta", "alpha"],
        ["n"],
        tty_in=True,
    )
    assert_preview(
        label.both,
        "acme/api",
        "412",
        "DELETE",
        f"{LABELS}/alpha",
        f"{LABELS}/zeta",
        "POST",
        LABELS,
        compact_json({"labels": ["a", "b"]}),
    )
    text = compact(label.both)
    assert (
        text.index(f"{LABELS}/alpha")
        < text.index(f"{LABELS}/zeta")
        < text.rindex(compact_json({"labels": ["a", "b"]}))
    )
    merge = env.direct(
        ["merge", "acme/api#412", "--method", "rebase"], ["n"], tty_in=True
    )
    assert_preview(
        merge.both,
        "acme/api",
        "412",
        "PUT",
        MERGE,
        compact_json({"merge_method": "rebase"}),
    )
    comment = env.direct(["comment", "acme/api#412", BODY], ["n"], tty_in=True)
    assert_preview(comment.both, "acme/api", "412", "POST", COMMENTS, BODY)
    approve = env.direct(["approve", "acme/api#412", BODY], ["n"], tty_in=True)
    assert_preview(approve.both, "acme/api", "412", "POST", REVIEWS, "APPROVE", BODY)
    assert env.github.writes == []


def test_g12_model_previews_are_complete(env: Env) -> None:
    env.github.prs[("acme/api", 412)].labels = ["alpha", "zeta"]
    env.model.push(
        call(
            (
                "l",
                "label",
                {"pr": "acme/api#412", "add": ["b", "a"], "remove": ["zeta", "alpha"]},
            ),
            ("m", "merge", {"pr": "acme/api#412", "method": "squash"}),
            ("c", "comment", {"pr": "acme/api#412", "body": BODY}),
            ("p", "approve", {"pr": "acme/api#412", "body": BODY}),
        ),
        say("ok"),
    )
    run = env.chat(["all of it", "n", "n", "n", "n"])
    assert_clean(run)
    assert run.both.count("[y/N]") == 4
    assert_preview(
        run.both,
        f"{LABELS}/alpha",
        f"{LABELS}/zeta",
        compact_json({"labels": ["a", "b"]}),
        MERGE,
        compact_json({"merge_method": "squash"}),
        COMMENTS,
        REVIEWS,
        "APPROVE",
    )
    assert compact(run.both).count(compact(BODY)) >= 2
    assert env.github.writes == []


# ---- gates 13 and 14: rules --------------------------------------------


def test_g13_rule_matches_only_the_exact_repo_and_label_sets(env: Env) -> None:
    env.github.add_queued("acme/web", 7, datetime.now(UTC) - timedelta(days=1))
    added = env.direct(
        ["rules", "add", "acme/api", "--add", "bug", "ui", "--remove", "low"]
    )
    assert_clean(added)

    exact = env.direct(
        ["label", "acme/api#20", "--add", "ui", "bug", "--remove", "low"],
        [],
        tty_in=True,
    )
    assert_clean(exact)
    assert "[y/N]" not in exact.both
    assert [(m, p) for m, p, _ in env.github.write_calls()] == [
        ("DELETE", "/repos/acme/api/issues/20/labels/low"),
        ("POST", "/repos/acme/api/issues/20/labels"),
    ]

    env.github.writes.clear()
    for argv in (
        ["label", "acme/api#412", "--add", "bug"],
        ["label", "acme/api#412", "--add", "bug", "ui"],
        ["label", "acme/api#412", "--add", "bug", "ui", "extra", "--remove", "low"],
        ["label", "acme/api#412", "--add", "bug", "--remove", "low", "ui"],
        ["label", "acme/web#7", "--add", "bug", "ui", "--remove", "low"],
    ):
        run = env.direct(argv, [EOF], tty_in=True)
        assert run.both.count("[y/N]") == 1, argv
    assert env.github.writes == []


def test_g13_rules_never_match_tier3(env: Env) -> None:
    assert_clean(env.direct(["rules", "add", "acme/api", "--add", "bug"]))
    for argv in (
        ["merge", "acme/api#412", "--method", "merge"],
        ["comment", "acme/api#412", "bug"],
        ["approve", "acme/api#412"],
    ):
        run = env.direct(argv, [EOF], tty_in=True)
        assert run.both.count("[y/N]") == 1, argv
    for bad in (
        ["rules", "add", "acme/api", "--merge"],
        ["rules", "add", "acme/api", "--method", "squash"],
        ["rules", "add", "acme/api"],
    ):
        assert env.direct(bad).code != 0, bad
    assert env.github.writes == []


def rule_ids(text: str, repo: str) -> list[int]:
    return [
        int(n)
        for line in text.splitlines()
        if repo in line
        for n in re.findall(r"\b\d+\b", line)
    ]


def test_g13_rule_ids_are_stable(env: Env) -> None:
    assert_clean(env.direct(["rules", "add", "acme/api", "--add", "bug"]))
    assert_clean(env.direct(["rules", "add", "acme/web", "--add", "ui"]))
    listing = env.direct(["rules", "list"])
    assert_clean(listing)
    [first] = rule_ids(listing.out, "acme/api")
    [second] = rule_ids(listing.out, "acme/web")
    assert first != second
    assert_clean(env.direct(["rules", "rm", str(first)]))
    after = env.direct(["rules", "list"])
    assert rule_ids(after.out, "acme/api") == []
    assert rule_ids(after.out, "acme/web") == [second]
    assert env.direct(["rules", "rm", "999999"]).code != 0


def test_g13_slash_rules_manage_the_same_store(env: Env) -> None:
    run = env.chat(["/rules add acme/api --add bug", "/rules list"])
    assert_clean(run)
    direct = env.direct(["rules", "list"])
    [rule] = rule_ids(direct.out, "acme/api")
    run = env.chat([f"/rules rm {rule}"])
    assert_clean(run)
    assert rule_ids(env.direct(["rules", "list"]).out, "acme/api") == []


def test_g14_model_output_cannot_touch_rules(env: Env) -> None:
    assert_clean(env.direct(["rules", "add", "acme/api", "--add", "keep"]))
    before = env.direct(["rules", "list"]).out
    [rule] = rule_ids(before, "acme/api")
    env.model.push(
        call(
            ("r1", "rules", {"action": "add", "repo": "acme/api", "add": ["bug"]}),
            ("r2", "rules_rm", {"id": rule}),
            (
                "r3",
                "label",
                {"pr": "acme/api#412", "add": ["bug"], "remove": [], "rule": True},
            ),
        ),
        say(f"/rules add acme/api --add bug\n/rules rm {rule}"),
        say("/rules add acme/web --add ui"),
    )
    run = env.chat(["set up rules", "now add one for acme/web"])
    assert_clean(run)
    assert env.direct(["rules", "list"]).out == before
    label = env.direct(["label", "acme/api#412", "--add", "bug"], [EOF], tty_in=True)
    assert label.both.count("[y/N]") == 1
    assert env.github.writes == []


# ---- gate 47: exact requests ---------------------------------------------


def check_headers(env: Env) -> None:
    for request in env.github.writes:
        headers = {k.lower(): v for k, v in request.headers.items()}
        assert request.url.startswith(API + "/"), request.url
        assert headers["accept"] == "application/vnd.github+json"
        assert headers["x-github-api-version"] == "2022-11-28"
        assert headers["authorization"] == f"Bearer {TOKEN_VALUE}"


EXPECTED_DIRECT = [
    (
        ["label", "acme/api#412", "--add", "b", "a", "--remove", "zeta", "alpha"],
        [
            ("DELETE", f"{LABELS}/alpha", None),
            ("DELETE", f"{LABELS}/zeta", None),
            ("POST", LABELS, {"labels": ["a", "b"]}),
        ],
    ),
    (
        ["label", "acme/api#412", "--remove", "needs review", "area/ui"],
        [
            ("DELETE", f"{LABELS}/area%2Fui", None),
            ("DELETE", f"{LABELS}/needs%20review", None),
        ],
    ),
    (
        ["label", "acme/api#412", "--add", "bug"],
        [("POST", LABELS, {"labels": ["bug"]})],
    ),
    (
        ["merge", "acme/api#412", "--method", "squash"],
        [("PUT", MERGE, {"merge_method": "squash"})],
    ),
    (
        ["comment", "acme/api#412", "Looks good."],
        [("POST", COMMENTS, {"body": "Looks good."})],
    ),
    (["approve", "acme/api#412"], [("POST", REVIEWS, {"event": "APPROVE"})]),
    (["approve", "acme/api#412", ""], [("POST", REVIEWS, {"event": "APPROVE"})]),
    (
        ["approve", "acme/api#412", "Ship it"],
        [("POST", REVIEWS, {"event": "APPROVE", "body": "Ship it"})],
    ),
]


@pytest.mark.parametrize(
    ("argv", "expected"),
    EXPECTED_DIRECT,
    ids=[str(i) for i in range(len(EXPECTED_DIRECT))],
)
def test_g47_direct_actions_send_exact_requests(
    env: Env, argv: list[str], expected: list[Any]
) -> None:
    env.github.prs[("acme/api", 412)].labels = [
        "alpha",
        "zeta",
        "needs review",
        "area/ui",
    ]
    run = env.direct(argv, ["y"], tty_in=True)
    assert_clean(run)
    assert env.github.write_calls() == expected
    check_headers(env)


TOOL_CALLS = [
    (
        "label",
        {"pr": "acme/api#412", "add": ["b", "a"], "remove": ["zeta", "alpha"]},
        0,
    ),
    ("merge", {"pr": "acme/api#412", "method": "squash"}, 3),
    ("comment", {"pr": "acme/api#412", "body": "Looks good."}, 4),
    ("approve", {"pr": "acme/api#412"}, 5),
    ("approve", {"pr": "acme/api#412", "body": ""}, 6),
    ("approve", {"pr": "acme/api#412", "body": "Ship it"}, 7),
]


@pytest.mark.parametrize(
    ("name", "args", "index"), TOOL_CALLS, ids=[f"{t[0]}-{t[2]}" for t in TOOL_CALLS]
)
def test_g47_tool_actions_match_direct(
    env: Env, name: str, args: dict[str, Any], index: int
) -> None:
    env.github.prs[("acme/api", 412)].labels = ["alpha", "zeta"]
    env.model.push(call(("w1", name, args)), say("done"))
    run = env.chat(["do it", "y"])
    assert_clean(run)
    assert env.github.write_calls() == EXPECTED_DIRECT[index][1]
    check_headers(env)


# ---- gate 48: dry run ----------------------------------------------------


DRY = [
    (
        [
            "label",
            "acme/api#412",
            "--add",
            "b",
            "a",
            "--remove",
            "zeta",
            "alpha",
            "--dry-run",
        ],
        [
            f"DELETE {LABELS}/alpha",
            f"DELETE {LABELS}/zeta",
            f"POST {LABELS}",
            compact_json({"labels": ["a", "b"]}),
        ],
    ),
    (
        ["merge", "acme/api#412", "--method", "rebase", "--dry-run"],
        [f"PUT {MERGE}", compact_json({"merge_method": "rebase"})],
    ),
    (
        ["comment", "acme/api#412", "Nice \x1b[2Jwork", "--dry-run"],
        [f"POST {COMMENTS}", "Nice", "work"],
    ),
    (
        ["approve", "acme/api#412", "Ship it", "--dry-run"],
        [f"POST {REVIEWS}", compact_json({"event": "APPROVE", "body": "Ship it"})],
    ),
]


def in_order(text: str, parts: list[str]) -> None:
    flat = compact(text)
    position = -1
    for part in parts:
        found = flat.find(compact(part), position + 1)
        assert found > position, (part, text)
        position = found


@pytest.mark.parametrize(("argv", "parts"), DRY, ids=[a[0] for a, _ in DRY])
def test_g48_dry_run_prints_requests_and_sends_nothing(
    env: Env, argv: list[str], parts: list[str]
) -> None:
    env.github.prs[("acme/api", 412)].labels = ["alpha", "zeta"]
    before = listed(env)
    run = env.direct(argv, ["y"], tty_in=True)
    assert_clean(run)
    in_order(run.out, parts)
    assert "\x1b" not in run.both
    assert env.github.writes == []
    assert env.github.prs[("acme/api", 412)].labels == ["alpha", "zeta"]
    assert listed(env) == before


# ---- gates 49 and 50: failed writes -------------------------------------


def success_tail(env: Env, argv: list[str]) -> str:
    run = env.direct(argv, ["y"], tty_in=True)
    assert_clean(run)
    lines = [line for line in after_answer(run).splitlines() if line.strip()]
    assert lines, run.both
    env.github.writes.clear()
    return lines[-1].strip()


def test_g49_partial_label_failure_reports_progress(env: Env) -> None:
    argv = ["label", "acme/api#412", "--add", "c", "--remove", "alpha", "beta"]
    env.github.prs[("acme/api", 412)].labels = ["alpha", "beta"]
    done = success_tail(env, argv)
    env.github.prs[("acme/api", 412)].labels = ["alpha", "beta"]
    env.github.fail_write("DELETE", f"{LABELS}/beta", Failure(status=500))
    run = env.direct(argv, ["y"], tty_in=True)
    assert not run.crash, run.crash
    assert run.code != 0
    assert [(m, p) for m, p, _ in env.github.write_calls()] == [
        ("DELETE", f"{LABELS}/alpha"),
        ("DELETE", f"{LABELS}/beta"),
    ]
    report = after_answer(run)
    assert f"{LABELS}/alpha" in report
    assert f"{LABELS}/beta" in report
    assert done not in report


FAILS = [
    (["merge", "acme/api#412", "--method", "squash"], "PUT", MERGE, 405),
    (["merge", "acme/api#412", "--method", "squash"], "PUT", MERGE, 307),
    (["comment", "acme/api#412", "hello"], "POST", COMMENTS, 403),
    (["approve", "acme/api#412"], "POST", REVIEWS, 422),
    (["label", "acme/api#412", "--add", "bug"], "POST", LABELS, 500),
    (["label", "acme/api#412", "--add", "bug"], "POST", LABELS, 404),
]


@pytest.mark.parametrize(
    ("argv", "method", "path", "status"),
    FAILS,
    ids=[f"{f[0][0]}-{f[3]}" for f in FAILS],
)
def test_g50_non_2xx_write_fails(
    env: Env, argv: list[str], method: str, path: str, status: int
) -> None:
    done = success_tail(env, argv)
    headers = {"Location": f"{API}/elsewhere"} if status == 307 else {}
    env.github.fail_write(method, path, Failure(status=status, headers=headers))
    run = env.direct(argv, ["y"], tty_in=True)
    assert not run.crash, run.crash
    assert run.code != 0
    assert len(env.github.writes) == 1
    assert done not in after_answer(run)


def test_g50_tool_write_failure_is_not_success(env: Env) -> None:
    env.github.fail_write("PUT", MERGE, Failure(status=405))
    env.model.push(
        call(("w1", "merge", {"pr": "acme/api#412", "method": "squash"})), say("done")
    )
    run = env.chat(["merge", "y"])
    assert_clean(run)
    result = json.loads(env.model.seen[1].tool_results()["w1"])
    assert "405" in json.dumps(result) or "fail" in json.dumps(result).lower()
    assert len(env.github.writes) == 1


# ---- gate 55: hide, unhide, snooze --------------------------------------


def test_g55_hide_until_unhide(env: Env) -> None:
    assert_clean(env.direct(["hide", "acme/api#30"]))
    assert 30 not in listed(env)
    time.sleep(1.0)
    assert 30 not in listed(env)
    assert_clean(env.direct(["unhide", "acme/api#30"]))
    assert 30 in listed(env)
    assert env.github.writes == []


def test_g55_snooze_expires(env: Env) -> None:
    until = datetime.now(UTC) + timedelta(seconds=3)
    stamp = until.replace(microsecond=0) + timedelta(seconds=1)
    assert_clean(env.direct(["snooze", "acme/api#21", stamp.isoformat()]))
    assert 21 not in listed(env)
    while datetime.now(UTC) <= stamp:
        time.sleep(0.2)
    time.sleep(0.3)
    assert 21 in listed(env)


@pytest.mark.parametrize(
    "stamp",
    [
        (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="seconds"),
        "2099-01-01T00:00:00",
        "2099-01-01",
        "tomorrow",
        "",
    ],
)
def test_g55_snooze_rejects_bad_times(env: Env, stamp: str) -> None:
    run = env.direct(["snooze", "acme/api#21", stamp])
    assert not run.crash, run.crash
    assert run.code != 0
    assert 21 in listed(env)


def test_g55_snooze_accepts_offsets(env: Env) -> None:
    later = datetime.now(UTC) + timedelta(days=2)
    stamp = later.astimezone().replace(microsecond=0).isoformat()
    assert re.search(r"[+-]\d\d:\d\d$", stamp)
    assert_clean(env.direct(["snooze", "acme/api#21", stamp]))
    assert 21 not in listed(env)
    assert_clean(
        env.direct(["snooze", "acme/api#20", future(3600).replace("+00:00", "Z")])
    )
    assert 20 not in listed(env)


def test_g55_filtering_happens_before_the_overlay(env: Env) -> None:
    env.model.push(
        call(
            ("m1", "move", {"pr": "acme/api#30", "position": "top", "reason": "urgent"})
        ),
        say("moved"),
    )
    run = env.chat(
        [
            "move 30",
            "/list 50",
            "/hide acme/api#30",
            "/list 50",
            "/unhide acme/api#30",
            "/list 50",
        ]
    )
    assert_clean(run)
    segments = run.segments()
    moved = [n for n, _, _ in primary_rows(segments[1])]
    hidden = [n for n, _, _ in primary_rows(segments[3])]
    back = [n for n, _, _ in primary_rows(segments[5])]
    assert moved[0] == 30
    assert hidden == [n for n in moved if n != 30]
    assert back == moved
    assert "[moved by AI]" in segments[5]
    assert PROMPT in run.out


# ---- gate 74: BROWSER without %s, and a missing browser ------------------

PR_URL = "https://github.com/acme/api/pull/412"
SUCCESS_WORDS = re.compile(r"(?i)\b(opened|complete|success)")


def arg_logger(env: Env) -> tuple[Path, Path]:
    """A browser script that logs each call's arguments as one `|`-joined line."""
    log = env.dirs["home"] / "browser-args.log"
    script = env.dirs["bin"] / "log-browser-args"
    script.write_text(f'#!/bin/sh\nprintf "%s|" "$@" >> "{log}"\necho >> "{log}"\n')
    script.chmod(0o755)
    return script, log


def browser_calls(log: Path, settle: float = 1.0) -> list[list[str]]:
    time.sleep(settle)
    if not log.exists():
        return []
    return [line.rstrip("|").split("|") for line in log.read_text().splitlines()]


def open_via(env: Env, via: str) -> Any:
    if via == "direct":
        return env.direct(["open", "acme/api#412"])
    if via == "slash":
        return env.chat(["/open acme/api#412", "/list"])
    env.model.push(call(("o1", "open", {"pr": "acme/api#412"})), say("done here"))
    return env.chat(["open 412", "/list"])


@pytest.mark.parametrize("extra", [[], ["--new-window"]], ids=["bare", "with_flag"])
@pytest.mark.parametrize("via", ["direct", "slash", "tool"])
def test_g74_browser_without_placeholder_gets_the_url_last(
    env: Env, monkeypatch: pytest.MonkeyPatch, via: str, extra: list[str]
) -> None:
    script, log = arg_logger(env)
    monkeypatch.setenv("BROWSER", " ".join([str(script), *extra]))
    run = open_via(env, via)
    assert_clean(run)
    assert browser_calls(log) == [[*extra, PR_URL]]
    assert env.github.writes == []


@pytest.mark.parametrize(
    "browser",
    ["no-such-browser-7731", "/nonexistent/dir/browser %s"],
    ids=["not_on_path", "bad_path_with_placeholder"],
)
@pytest.mark.parametrize("via", ["direct", "slash", "tool"])
def test_g74_missing_browser_is_a_short_error(
    env: Env, monkeypatch: pytest.MonkeyPatch, via: str, browser: str
) -> None:
    ok_result = None
    if via == "tool":
        script, _log = arg_logger(env)
        monkeypatch.setenv("BROWSER", str(script))
        assert_clean(open_via(env, via))
        ok_result = env.model.seen[-1].tool_results()["o1"]
    monkeypatch.setenv("BROWSER", browser)
    start = len(env.model.seen)
    run = open_via(env, via)
    assert_clean(run, 1 if via == "direct" else 0)
    assert not SUCCESS_WORDS.search(run.both), run.both
    for line in run.both.splitlines():
        assert len(line) <= 80, line
    if via == "tool":
        result = env.model.seen[start + 1].tool_results()["o1"]
        assert result != ok_result, result
    else:
        error = run.err.strip()
        assert error != "" and "\n" not in error and len(error) <= 80, run.err
    if via != "direct":
        assert primary_rows(run.out)  # chat is still usable
    assert env.github.writes == []
