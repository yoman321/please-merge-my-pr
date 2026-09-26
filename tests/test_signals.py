"""Gates for the seven signals and the score formula: C24, and C22 rank order.

Planned gates 45, 46, 75, and 76 of plans/chat.md.
"""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import chat_harness
import pytest
from chat_harness import (
    ALIASES,
    DEFAULT_WEIGHTS,
    WEIGHT_KEYS,
    Env,
    assert_clean,
)
from conftest import API
from fake_github import Failure
from fake_github_plus import BlockedIssue, FakeGitHubPlus

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture

TOL = 1e-4


def world(**pr: Any) -> FakeGitHubPlus:
    fake = FakeGitHubPlus(API)
    requested = pr.pop("requested", datetime.now(UTC) - timedelta(days=7))
    files = pr.pop("files", [("src/app.py", 10, 0)])
    fake.add_queued("acme/api", 412, requested, files=files, **pr)
    return fake


def why(env: Env, fake: FakeGitHubPlus) -> dict[str, Any]:
    env.github = fake
    run = env.direct(["why", "acme/api#412", "--json"])
    assert_clean(run)
    return dict(json.loads(run.out))


def rows(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {}
    for row in detail["rows"]:
        name = row["name"]
        canonical = next((k for k, v in ALIASES.items() if v == name), name)
        out[canonical] = row
    assert set(out) == set(WEIGHT_KEYS), sorted(out)
    return out


def value(env: Env, fake: FakeGitHubPlus, signal: str) -> float:
    return float(rows(why(env, fake))[signal]["value"])


def check_formula(detail: dict[str, Any], weights: dict[str, float]) -> None:
    by_name = rows(detail)
    total = sum(weights.values())
    assert abs(sum(r["weight"] for r in by_name.values()) - total) < 1e-9
    exact = 0.0
    for name, row in by_name.items():
        assert math.isfinite(row["value"]) and 0.0 <= row["value"] <= 1.0, (name, row)
        assert row["weight"] == weights[name]
        expected = 100.0 * (weights[name] / total) * row["value"]
        assert abs(row["points"] - expected) < 1e-9, (name, row)
        exact += expected
    assert abs(detail["exact"] - exact) < 1e-9
    assert detail["score"] == math.floor(detail["exact"] + 0.5)


# ---- gate 45: signal formulas ------------------------------------------


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([], 0.0),
        (["High"], 0.75),
        (["urgent", "low"], 1.0),
        (["MEDIUM", "low"], 0.5),
        (["low"], 0.25),
        (["urgently", "HIGHER", "not-low"], 0.0),
    ],
)
def test_g45_urgency(env: Env, labels: list[str], expected: float) -> None:
    assert value(env, world(labels=labels), "urgency") == expected


def blocks_world(
    issues: list[BlockedIssue] | None = None,
    stacked: list[tuple[str, str, list[str]]] | None = None,
) -> FakeGitHubPlus:
    fake = world(author="alice", head_ref="feat-x")
    fake.more("acme/api", 412).blocking = list(issues or [])
    for index, (base, author, assignees) in enumerate(stacked or []):
        fake.add_stacked("acme/api", 900 + index, base, author, assignees)
    return fake


BLOCKS = [
    ("none", [], [], 0.0),
    ("one assignee", [BlockedIssue("acme/api", 5, ["carol"])], [], 1 / 3),
    ("other repo excluded", [BlockedIssue("acme/web", 5, ["erin"])], [], 0.0),
    ("author excluded", [BlockedIssue("acme/api", 5, ["alice"])], [], 0.0),
    (
        "distinct across both sources",
        [
            BlockedIssue("acme/api", 5, ["carol", "dave"]),
            BlockedIssue("acme/api", 6, ["carol"]),
        ],
        [("feat-x", "frank", ["carol", "alice"])],
        1.0,
    ),
    ("stack author and assignee", [], [("feat-x", "frank", ["gina"])], 2 / 3),
    ("stack on another branch", [], [("main", "frank", ["gina"])], 0.0),
    ("stack by the author", [], [("feat-x", "alice", [])], 0.0),
    (
        "over cap",
        [BlockedIssue("acme/api", 5, ["p1", "p2", "p3", "p4", "p5"])],
        [],
        1.0,
    ),
    ("at cap", [BlockedIssue("acme/api", 5, ["p1", "p2", "p3"])], [], 1.0),
]


@pytest.mark.parametrize(
    ("issues", "stacked", "expected"),
    [b[1:] for b in BLOCKS],
    ids=[b[0] for b in BLOCKS],
)
def test_g45_blocks(
    env: Env, issues: list[BlockedIssue], stacked: list[Any], expected: float
) -> None:
    assert abs(value(env, blocks_world(issues, stacked), "blocks") - expected) < 1e-9


def test_g45_blocks_cap_is_configurable(env: Env) -> None:
    from chat_harness import canonical_config, install_config

    text = canonical_config(model_url=env.model.base_url).replace(
        "blocked_people_cap = 3.0", "blocked_people_cap = 2.0"
    )
    install_config(env.dirs, text)
    fake = blocks_world([BlockedIssue("acme/api", 5, ["carol"])])
    assert abs(value(env, fake, "blocks") - 0.5) < 1e-9


@pytest.mark.parametrize("source", ["blocking", "stack"])
def test_g45_blocks_one_failed_source_is_unavailable(env: Env, source: str) -> None:
    fake = blocks_world(
        [BlockedIssue("acme/api", 5, ["carol"])], [("feat-x", "frank", [])]
    )
    fake.fail(
        source, Failure(status=500), "acme/api", 412 if source == "blocking" else None
    )
    detail = why(env, fake)
    row = rows(detail)["blocks"]
    assert (row["status"], row["value"], row["points"]) == ("unavailable", 0.0, 0.0)
    assert row["weight"] == 25.0
    check_formula(detail, DEFAULT_WEIGHTS)


def due_world(due: timedelta | None, milestone: bool = True) -> FakeGitHubPlus:
    fake = world()
    extra = fake.more("acme/api", 412)
    extra.milestone = milestone
    extra.milestone_due = None if due is None else datetime.now(UTC) + due
    return fake


@pytest.mark.parametrize(
    ("due", "milestone", "expected"),
    [
        (None, False, 0.0),
        (None, True, 0.0),
        (timedelta(days=-1), True, 1.0),
        (timedelta(days=7), True, 0.5),
        (timedelta(days=3.5), True, 0.75),
        (timedelta(days=14, hours=1), True, 0.0),
        (timedelta(days=30), True, 0.0),
    ],
)
def test_g45_due_soon(
    env: Env, due: timedelta | None, milestone: bool, expected: float
) -> None:
    fake = due_world(due, milestone)
    assert abs(value(env, fake, "due_soon") - expected) < TOL


@pytest.mark.parametrize(
    ("requested", "created", "expected"),
    [
        (timedelta(days=7), timedelta(days=100), 0.5),
        (timedelta(days=7), timedelta(days=8), 0.5),
        (timedelta(days=14), timedelta(days=30), 1.0),
        (timedelta(days=40), timedelta(days=41), 1.0),
        (timedelta(hours=-1), timedelta(days=1), 0.0),
    ],
)
def test_g45_age_unchanged(
    env: Env, requested: timedelta, created: timedelta, expected: float
) -> None:
    now = datetime.now(UTC)
    fake = world(requested=now - requested, created_at=now - created)
    assert abs(value(env, fake, "age") - expected) < TOL


@pytest.mark.parametrize(
    ("files", "additions", "expected"),
    [
        ([("src/a.py", 100, 50)], None, 0.3),
        ([("src/a.py", 100, 0), ("uv.lock", 1000, 0)], None, 0.2),
        ([("src/a.py", 100, 0), ("web/package-lock.json", 50, 50)], None, 0.2),
        ([("src/a.py", 10, 0), ("uv.lock", 1000, 0)], 5, 0.0),
        ([("src/a.py", 800, 0)], None, 1.0),
        ([("src/a.py", 500, 0)], None, 1.0),
        ([], None, 0.0),
    ],
)
def test_g45_diff_unchanged(
    env: Env, files: list[tuple[str, int, int]], additions: int | None, expected: float
) -> None:
    fake = world(
        files=files,
        additions=additions,
        **({"deletions": 0} if additions is not None else {}),
    )
    assert abs(value(env, fake, "diff") - expected) < 1e-9


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("auth/session.py", 1.0),
        ("billing/x/y.py", 1.0),
        ("migrations/1.sql", 1.0),
        ("src/auth.py", 0.0),
    ],
)
def test_g45_risk_unchanged(env: Env, path: str, expected: float) -> None:
    assert value(env, world(files=[(path, 1, 0)]), "risk") == expected


@pytest.mark.parametrize(
    ("rollup", "mergeable", "expected"),
    [
        ("SUCCESS", True, 1.0),
        ("PENDING", True, 1.0),
        (None, True, 1.0),
        ("FAILURE", True, 0.0),
        ("SUCCESS", False, 0.0),
        ("PENDING", False, 0.0),
    ],
)
def test_g45_ci_unchanged(
    env: Env, rollup: str | None, mergeable: bool, expected: float
) -> None:
    assert value(env, world(rollup=rollup, mergeable=mergeable), "ci") == expected


# ---- gate 46: the formula ------------------------------------------------


def rich_world() -> FakeGitHubPlus:
    fake = world(
        labels=["high"],
        files=[("auth/a.py", 200, 50), ("uv.lock", 30, 0)],
        head_ref="feat-x",
        rollup="PENDING",
    )
    fake.more("acme/api", 412).blocking = [BlockedIssue("acme/api", 5, ["carol"])]
    fake.more("acme/api", 412).milestone_due = datetime.now(UTC) + timedelta(days=7)
    return fake


WEIGHT_SETS = [
    DEFAULT_WEIGHTS,
    {
        "urgency": 0.0,
        "blocks": 0.0,
        "risk": 20.0,
        "due_soon": 0.0,
        "age": 10.0,
        "diff": 10.0,
        "ci": 0.0,
    },
    {
        "urgency": 1.0,
        "blocks": 1.0,
        "risk": 1.0,
        "due_soon": 1.0,
        "age": 1.0,
        "diff": 1.0,
        "ci": 1.0,
    },
    {
        "urgency": 100.0,
        "blocks": 0.0,
        "risk": 0.0,
        "due_soon": 0.0,
        "age": 0.0,
        "diff": 0.0,
        "ci": 0.0,
    },
]


@pytest.mark.parametrize(
    "weights", WEIGHT_SETS, ids=["default", "rescaled", "equal", "single"]
)
def test_g46_contributions_follow_the_formula(
    env: Env, weights: dict[str, float]
) -> None:
    from chat_harness import canonical_config, install_config

    install_config(
        env.dirs, canonical_config(model_url=env.model.base_url, weights=weights)
    )
    detail = why(env, rich_world())
    check_formula(detail, weights)
    by_name = rows(detail)
    assert by_name["urgency"]["value"] == 0.75
    assert abs(by_name["blocks"]["value"] - 1 / 3) < 1e-9
    assert by_name["risk"]["value"] == 1.0
    assert abs(by_name["due_soon"]["value"] - 0.5) < TOL
    assert abs(by_name["age"]["value"] - 0.5) < TOL
    assert abs(by_name["diff"]["value"] - 0.5) < 1e-9
    assert by_name["ci"]["value"] == 1.0


def test_g46_default_score_matches_the_written_formula(env: Env) -> None:
    detail = why(env, rich_world())
    s = {k: r["value"] for k, r in rows(detail).items()}
    written = (
        30 * s["urgency"]
        + 25 * s["blocks"]
        + 15 * s["risk"]
        + 10 * s["due_soon"]
        + 10 * s["age"]
        + 5 * s["diff"]
        + 5 * s["ci"]
    )
    assert abs(detail["exact"] - written) < 1e-9
    assert detail["score"] == math.floor(written + 0.5)


@pytest.mark.parametrize(
    ("kind", "signals"),
    [
        ("files", ("risk", "diff")),
        ("graphql_ci", ("ci",)),
    ],
)
def test_g46_unavailable_reads_keep_their_weight(
    env: Env, kind: str, signals: tuple[str, ...]
) -> None:
    fake = rich_world()
    fake.fail(kind, Failure(status=500), "acme/api", 412)
    detail = why(env, fake)
    for name in signals:
        row = rows(detail)[name]
        assert (row["status"], row["value"], row["points"]) == (
            "unavailable",
            0.0,
            0.0,
        ), name
        assert row["weight"] == DEFAULT_WEIGHTS[name]
    check_formula(detail, DEFAULT_WEIGHTS)


def test_g46_rank_order_ties(env: Env) -> None:
    now = datetime.now(UTC)
    fake = FakeGitHubPlus(API)
    older = now - timedelta(days=7, minutes=1)
    same = now - timedelta(days=7)
    for repo, number, requested in (
        ("acme/web", 3, same),
        ("acme/api", 9, same),
        ("acme/api", 4, same),
        ("acme/zzz", 50, older),
    ):
        fake.add_queued(repo, number, requested, files=[("src/a.py", 10, 0)])
    env.github = fake
    run = env.direct(["list", "--all", "--json"])
    assert_clean(run)
    items = json.loads(run.out)["items"]
    assert len({i["score"] for i in items}) == 1
    assert [(i["repo"], i["number"]) for i in items] == [
        ("acme/zzz", 50),
        ("acme/api", 4),
        ("acme/api", 9),
        ("acme/web", 3),
    ]


# ---- gate 75: a fork head skips the stack source -------------------------


class ForkGitHub(FakeGitHubPlus):
    """PRs named in `forks` have their head branch in another repository."""

    def __init__(self, api_url: str) -> None:
        super().__init__(api_url)
        self.forks: dict[tuple[str, int], str] = {}

    def _pull_json(self, pr: Any) -> dict[str, Any]:
        out = super()._pull_json(pr)
        fork = self.forks.get((pr.repo, pr.number))
        if fork is not None:
            owner, name = fork.split("/")
            head_repo = {
                **out["head"]["repo"],
                "id": out["head"]["repo"]["id"] + 1,
                "name": name,
                "full_name": fork,
                "owner": self._user(owner),
                "url": f"{self.payload_base}/repos/{fork}",
                "html_url": f"{self.payload_base}/{fork}",
            }
            out["head"] = {
                **out["head"],
                "label": f"{owner}:{pr.head_ref}",
                "user": self._user(owner),
                "repo": head_repo,
            }
        return out


def stack_world(fork: str | None) -> ForkGitHub:
    """#412 from branch `main`; #900 is an open PR into `main` by frank and gina."""
    fake = ForkGitHub(API)
    fake.add_queued(
        "acme/api",
        412,
        datetime.now(UTC) - timedelta(days=7),
        files=[("src/app.py", 10, 0)],
        author="alice",
        head_ref="main",
    )
    if fork is not None:
        fake.forks[("acme/api", 412)] = fork
    fake.more("acme/api", 412).blocking = [BlockedIssue("acme/api", 5, ["carol"])]
    fake.add_stacked("acme/api", 900, "main", "frank", ["gina"])
    return fake


def pull_list_requests(fake: FakeGitHubPlus) -> list[str]:
    return [
        r.url
        for r in fake.requests
        if r.method.upper() == "GET"
        and re.fullmatch(r".*/repos/[^/]+/[^/]+/pulls", urlsplit(r.url).path)
    ]


@pytest.mark.parametrize("stack_fails", [False, True], ids=["stack_up", "stack_down"])
def test_g75_fork_head_skips_the_stack_source(env: Env, stack_fails: bool) -> None:
    same_repo = stack_world(None)
    row = rows(why(env, same_repo))["blocks"]
    assert abs(row["value"] - 1.0) < 1e-9  # carol, frank, gina
    assert pull_list_requests(same_repo) != []

    fork = stack_world("forker/api")
    if stack_fails:
        fork.fail("stack", Failure(status=500), "acme/api", None)
    detail = why(env, fork)
    row = rows(detail)["blocks"]
    assert pull_list_requests(fork) == []
    assert row["status"] != "unavailable", row
    assert abs(row["value"] - 1 / 3) < 1e-9, row  # carol only
    check_formula(detail, DEFAULT_WEIGHTS)


# ---- gate 76: age keeps fractional seconds -------------------------------


@pytest.mark.parametrize("seconds", [0.5, 1.5, 3599.75])
def test_g76_age_keeps_fractional_seconds(seconds: float) -> None:
    from conftest import NOW, make_event, make_reads, make_review, plan_config

    from please_merge_my_pr.scoring import score
    from please_merge_my_pr.signals import registry

    config = plan_config()
    reads = make_reads(
        review=make_review(requested_at=NOW - timedelta(seconds=seconds))
    )
    expected = seconds / (config.age_cap_days * 86400)
    result = registry()["age"](make_event(), reads, config, NOW)
    assert math.isclose(result.value, expected, rel_tol=1e-12), result
    scored = score(make_event(), reads, config.weights, config, NOW)
    age_row = next(r for r in scored.rows if r.name == "age")
    assert math.isclose(age_row.value, expected, rel_tol=1e-12), age_row
