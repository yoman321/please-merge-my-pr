"""Gate for I8."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import (
    API,
    UNAVAILABLE_REASONS,
    assert_ran,
    make_event,
    make_pr,
    make_reads,
    make_review,
    run_cli,
)
from fake_github import Failure, FakeGitHub

from please_merge_my_pr.events import Reads, Unavailable
from please_merge_my_pr.queue import In, Out, Unknown, eligible

CASES: list[tuple[str, Reads, type]] = [
    ("by-name request from a user", make_reads(), In),
    (
        "team-only request",
        make_reads(review=make_review(requested_at=None, by_name=False)),
        Out,
    ),
    # Accepted limit (decision 12): a team request GitHub turned into a named
    # request has the same fields as a manual one, so it is let in.
    (
        "team request surfaced as a named user",
        make_reads(review=make_review(by_name=True)),
        In,
    ),
    ("code-owner request", make_reads(review=make_review(as_code_owner=True)), Out),
    ("bot requester", make_reads(review=make_review(requested_by_user=False)), Out),
    ("draft", make_reads(pr=make_pr(draft=True)), Out),
    (
        "no current request",
        make_reads(review=make_review(requested_at=None, by_name=False)),
        Out,
    ),
]
CASES += [
    (f"review read {r}", make_reads(review=Unavailable(r)), Unknown)
    for r in UNAVAILABLE_REASONS
]
CASES += [
    (f"PR read {r}", make_reads(pr=Unavailable(r)), Unknown)
    for r in UNAVAILABLE_REASONS
]


@pytest.mark.parametrize(
    ("label", "reads", "expected"), CASES, ids=[c[0] for c in CASES]
)
def test_queue_entry(label: str, reads: Reads, expected: type) -> None:
    assert type(eligible(make_event(), reads)) is expected


def test_queue_entry_could_not_check(live: Mapping[str, Path]) -> None:
    now = datetime.now(UTC)
    fake = FakeGitHub(API)
    fake.add_queued("acme/api", 1, now - timedelta(days=2), files=[("src/a.py", 10, 0)])
    fake.add_queued("acme/api", 2, now - timedelta(days=2), files=[("src/b.py", 10, 0)])
    fake.add_queued(
        "acme/api", 3, now - timedelta(days=2), files=[("src/c.py", 10, 0)], draft=True
    )
    fake.fail(
        "timeline", Failure(status=500), "acme/api", 2
    )  # review read → Unavailable("server_error")

    data = run_cli(["list", "--json"], transport=fake)
    assert_ran(data)
    payload = json.loads(data.out)
    assert payload["could_not_check"] == 1
    assert payload["total"] == 1
    assert [(i["repo"], i["number"]) for i in payload["items"]] == [("acme/api", 1)]

    plain = run_cli(["list"], transport=fake)
    assert_ran(plain)
    header = plain.out.splitlines()[0]
    assert "1 in queue" in header
    assert "· 1 could not check" in header
