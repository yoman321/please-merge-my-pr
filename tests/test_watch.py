"""Gates for phase 7: I6, I7, and watch filtering (I8)."""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta
from pathlib import Path

from conftest import API, NOW, plan_config
from fake_github import FakeGitHub, ReviewRequest, TimelineEvent, lower_headers

from please_merge_my_pr.ingest.poll import Poller
from please_merge_my_pr.store import Store

CANARY = "QZXCANARY"
LM1 = "Thu, 24 Sep 2026 12:00:00 GMT"
LM2 = "Thu, 24 Sep 2026 12:01:00 GMT"
ETAG1 = 'W/"etag-one"'


def s(seconds: float) -> timedelta:
    return timedelta(seconds=seconds)


def new_poller(fake: FakeGitHub, db: Path) -> Poller:
    return Poller(fake, Store(db), plan_config(), "test-token")


def test_db_has_no_content(tmp_path: Path) -> None:
    fake = FakeGitHub(API)
    fake.add_queued(
        "acme/api",
        412,
        NOW - timedelta(days=7),
        files=[(f"auth/{CANARY}_path.py", 300, 80)],
        title=f"{CANARY}_title",
        body=f"{CANARY}_body",
        head_ref=f"{CANARY}_branch",
    )
    fake.queue_notifications(
        [fake.notification("acme/api", 412)], last_modified=LM1, etag=ETAG1
    )
    db = tmp_path / "state.sqlite3"

    items = new_poller(fake, db).poll_once(NOW)
    assert [(i.repo, i.number) for i in items] == [("acme/api", 412)]

    conn = sqlite3.connect(db)
    try:
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        assert tables
        found = []
        for name, sql in conn.execute("SELECT name, sql FROM sqlite_master"):
            if CANARY in f"{name} {sql}":
                found.append(("schema", name))
        for table in tables:
            columns = [c[1] for c in conn.execute(f'PRAGMA table_info("{table}")')]
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for column, value in zip(columns, row, strict=True):
                    text = (
                        value.decode("utf-8", "replace")
                        if isinstance(value, bytes)
                        else str(value)
                    )
                    if CANARY in text:
                        found.append((table, column))
    finally:
        conn.close()
    assert found == []


def test_poll_interval(tmp_path: Path) -> None:
    fake = FakeGitHub(API)
    for interval in (60, 60, 120, 120, 120):
        fake.queue_notifications([], last_modified=LM1, poll_interval=interval)
    db = tmp_path / "state.sqlite3"
    poller = new_poller(fake, db)

    def sent_at(t: float, p: Poller | None = None) -> int:
        before = len(fake.requests)
        (p or poller).poll_once(NOW + s(t))
        return len(fake.requests) - before

    assert sent_at(0) == 1
    assert [sent_at(t) for t in (0, 1, 30, 59, 59.999)] == [0, 0, 0, 0, 0]
    assert sent_at(60) == 1
    # A new poller on the same state still waits for the stored interval.
    restarted = new_poller(fake, db)
    assert [sent_at(t, restarted) for t in (60.5, 90, 119.9)] == [0, 0, 0]
    assert sent_at(120, restarted) == 1  # this answer raises the interval to 120 s
    assert [sent_at(t, restarted) for t in (180, 239.9)] == [0, 0]
    assert sent_at(240, restarted) == 1
    assert len(fake.notification_requests()) == len(fake.requests) == 4


def test_conditional_headers(tmp_path: Path) -> None:
    fake = FakeGitHub(API)
    fake.queue_notifications([], last_modified=LM1)  # no ETag yet
    fake.queue_notifications([], last_modified=LM2, etag=ETAG1)
    fake.queue_notifications(None, status=304)
    fake.queue_notifications(None, status=304)
    poller = new_poller(fake, tmp_path / "state.sqlite3")
    for t in (0, 60, 120, 180):
        poller.poll_once(NOW + s(t))

    sent = [lower_headers(r) for r in fake.notification_requests()]
    assert len(sent) == 4
    assert sent[1].get("if-modified-since") == LM1
    assert sent[2].get("if-modified-since") == LM2
    assert sent[2].get("if-none-match") == ETAG1
    assert sent[3].get("if-modified-since") == LM2
    assert sent[3].get("if-none-match") == ETAG1


def test_304_emits_nothing(tmp_path: Path) -> None:
    fake = FakeGitHub(API)
    fake.add_queued(
        "acme/api", 412, NOW - timedelta(days=7), files=[("auth/session.py", 300, 80)]
    )
    fake.queue_notifications(
        [fake.notification("acme/api", 412)], last_modified=LM1, etag=ETAG1
    )
    fake.queue_notifications(None, status=304)
    poller = new_poller(fake, tmp_path / "state.sqlite3")

    assert len(poller.poll_once(NOW)) == 1
    before = len(fake.requests)
    assert poller.poll_once(NOW + s(60)) == []
    assert len(fake.requests) - before == 1  # only the notifications request


def test_watch_filters_and_deduplicates(tmp_path: Path) -> None:
    fake = FakeGitHub(API)
    requested = NOW - timedelta(days=7)
    fake.add_queued("acme/api", 412, requested, files=[("auth/session.py", 300, 80)])
    fake.add_queued("acme/api", 413, requested, files=[("src/a.py", 10, 0)])
    fake.add_queued("acme/api", 415, requested, files=[("src/b.py", 10, 0)], draft=True)
    team_only = fake.add_queued("acme/api", 416, requested, files=[("src/c.py", 10, 0)])
    team_only.review_requests = [ReviewRequest("Team", "platform")]
    team_only.timeline = [TimelineEvent("review_requested", requested, team="platform")]
    notifications = [
        fake.notification("acme/api", 412),
        fake.notification("acme/api", 413, reason="mention"),
        fake.notification("acme/api", 414, kind="Issue"),
        fake.notification("acme/api", 415),
        fake.notification("acme/api", 416),
    ]
    for _ in range(5):
        fake.queue_notifications(notifications, last_modified=LM1)
    db = tmp_path / "state.sqlite3"
    poller = new_poller(fake, db)

    def keys(t: float, p: Poller | None = None) -> list[tuple[str, int]]:
        return [(i.repo, i.number) for i in (p or poller).poll_once(NOW + s(t))]

    first = poller.poll_once(NOW)
    assert [(i.repo, i.number) for i in first] == [("acme/api", 412)]
    assert first[0].score == 29
    assert first[0].reason == "touches auth · waiting 7d · 380 lines"
    for url in fake.urls():
        assert not re.search(r"/(pulls|issues)/41[34](/|$|\?)", url), url

    assert keys(60) == []  # the same request turn prints once
    fake.prs[("acme/api", 412)].timeline.append(
        TimelineEvent("review_requested", NOW + s(90), reviewer="me", requester="bob")
    )
    assert keys(120) == [("acme/api", 412)]  # a re-request is a new turn
    assert keys(180) == []
    assert keys(240, new_poller(fake, db)) == []  # remembered across restarts
