"""Gates for phase 5 reads (I8, I9) and I17."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

import pytest
from conftest import API, NOW, all_files, plan_config, run_cli, write_config
from fake_github import (
    Failure,
    FakeGitHub,
    FakePR,
    ReviewRequest,
    TimelineEvent,
    lower_headers,
)

from please_merge_my_pr.config import load_config
from please_merge_my_pr.events import Event, ReviewTurn, Unavailable
from please_merge_my_pr.github.http import Request, UrllibTransport
from please_merge_my_pr.github.read import Candidate, read_candidates
from please_merge_my_pr.ingest.poll import Poller
from please_merge_my_pr.store import Store

T1 = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 9, 12, 9, 0, tzinfo=UTC)
T3 = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def filler(n: int, start: datetime) -> list[TimelineEvent]:
    return [TimelineEvent("labeled", start + timedelta(minutes=i)) for i in range(n)]


def by_key(candidates: list[Candidate]) -> dict[tuple[str, int], Candidate]:
    return {(c.repo, c.number): c for c in candidates}


def big_world() -> FakeGitHub:
    fake = FakeGitHub(API, viewer="me")
    # #1: every list spans more than one page at any page size GitHub allows.
    files = [(f"src/f{i:03}.py", 1, 0) for i in range(129)] + [("auth/zz.py", 2, 1)]
    others = [ReviewRequest("User", f"user{i:03}") for i in range(100)]
    timeline = (
        filler(5, T1 - timedelta(days=1))
        + [TimelineEvent("review_requested", T1, reviewer="me", requester="bob")]
        + filler(44, T1)
        + [TimelineEvent("review_requested", T3, reviewer="carol", requester="bob")]
        + filler(59, T1)
        + [TimelineEvent("review_requested", T2, reviewer="me", requester="dave")]
        + filler(10, T3)
    )
    fake.add(
        FakePR(
            "acme/api",
            1,
            files=files,
            review_requests=[
                *others,
                ReviewRequest("Team", "platform"),
                ReviewRequest("User", "me"),
            ],
            timeline=timeline,
            rollup="SUCCESS",
        )
    )
    # #2: a team named like the viewer, and a user whose login only starts like it.
    fake.add(
        FakePR(
            "acme/api",
            2,
            review_requests=[
                ReviewRequest("User", "someone"),
                ReviewRequest("Team", "me"),
                ReviewRequest("User", "me-too"),
            ],
            timeline=[TimelineEvent("review_requested", T1, reviewer="someone")],
            rollup="FAILURE",
        )
    )
    # #3: the viewer is requested as a code owner.
    fake.add(
        FakePR(
            "acme/api",
            3,
            review_requests=[ReviewRequest("User", "me", as_code_owner=True)],
            timeline=[TimelineEvent("review_requested", T1, reviewer="me")],
            rollup=None,
        )
    )
    # #4: the latest matching request came from a bot.
    fake.add(
        FakePR(
            "acme/api",
            4,
            review_requests=[ReviewRequest("User", "me")],
            timeline=[
                TimelineEvent(
                    "review_requested",
                    T1,
                    reviewer="me",
                    requester="bob",
                    requester_type="User",
                ),
                TimelineEvent(
                    "review_requested",
                    T2,
                    reviewer="me",
                    requester="renovate[bot]",
                    requester_type="Bot",
                ),
            ],
            rollup="PENDING",
        )
    )
    # #5: a current request for the viewer, but no matching timeline event.
    fake.add(
        FakePR(
            "acme/api",
            5,
            review_requests=[ReviewRequest("User", "me")],
            timeline=[TimelineEvent("review_requested", T1, reviewer="someone")],
        )
    )
    # #6: GitHub is still computing mergeability.
    fake.add_queued("acme/api", 6, T1, mergeable=None)
    # Enough plain candidates that search needs more than one page of 100.
    for n in range(100, 200):
        fake.add_queued("acme/bulk", n, T1, files=[("src/x.py", 1, 0)])
    return fake


def test_github_reads() -> None:
    fake = big_world()
    candidates = read_candidates(fake, plan_config(), "test-token")
    got = by_key(candidates)

    assert len(candidates) == 106
    assert set(got) == set(fake.prs)
    for (repo, number), candidate in got.items():
        pr = fake.prs[(repo, number)]
        assert candidate.event == Event(repo, number, pr.base_ref, pr.head_ref)

    one = got[("acme/api", 1)].reads
    assert isinstance(one.files, tuple)
    assert len(one.files) == 130
    assert [f.path for f in one.files] == sorted(
        f[0] for f in fake.prs[("acme/api", 1)].files
    )
    assert one.review == ReviewTurn(
        requested_at=T2, by_name=True, as_code_owner=False, requested_by_user=True
    )
    assert one.ci == "passing"
    assert one.mergeable is True

    two = got[("acme/api", 2)].reads
    assert isinstance(two.review, ReviewTurn)
    assert two.review.by_name is False
    assert two.ci == "failing"

    three = got[("acme/api", 3)].reads
    assert isinstance(three.review, ReviewTurn)
    assert (three.review.by_name, three.review.as_code_owner) == (True, True)
    assert three.ci == "none"

    four = got[("acme/api", 4)].reads
    assert isinstance(four.review, ReviewTurn)
    assert (four.review.requested_at, four.review.requested_by_user) == (T2, False)
    assert four.ci == "pending"

    assert got[("acme/api", 5)].reads.review == Unavailable("unmatched")
    assert got[("acme/api", 6)].reads.mergeable == Unavailable("computing")

    for request in fake.requests:
        assert "test-token" not in request.url


FAILURES: list[tuple[str, str, Failure, str, str]] = [
    # (label, fake kind, failure, Reads field, expected reason)
    ("files 403", "files", Failure(status=403), "files", "forbidden"),
    ("files 404", "files", Failure(status=404), "files", "not_found"),
    (
        "files 429",
        "files",
        Failure(status=429, headers={"Retry-After": "30"}),
        "files",
        "rate_limited",
    ),
    (
        "files 403 rate limit",
        "files",
        Failure(
            status=403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"},
        ),
        "files",
        "rate_limited",
    ),
    ("files 500", "files", Failure(status=500), "files", "server_error"),
    ("files 503", "files", Failure(status=503), "files", "server_error"),
    (
        "files network",
        "files",
        Failure(raises=ConnectionError("connection refused")),
        "files",
        "network_error",
    ),
    (
        "files timeout",
        "files",
        Failure(raises=TimeoutError("timed out")),
        "files",
        "timeout",
    ),
    (
        "files bad json",
        "files",
        Failure(status=200, body=b"{not json"),
        "files",
        "invalid_response",
    ),
    ("timeline 500", "timeline", Failure(status=500), "review", "server_error"),
    ("timeline 404", "timeline", Failure(status=404), "review", "not_found"),
    (
        "graphql review 502",
        "graphql_review",
        Failure(status=502),
        "review",
        "server_error",
    ),
    (
        "graphql review bad json",
        "graphql_review",
        Failure(status=200, body=b"<html>"),
        "review",
        "invalid_response",
    ),
    (
        "graphql ci timeout",
        "graphql_ci",
        Failure(raises=TimeoutError("timed out")),
        "ci",
        "timeout",
    ),
    ("pull 404", "pull", Failure(status=404), "pr", "not_found"),
    ("pull 403", "pull", Failure(status=403), "pr", "forbidden"),
]


@pytest.mark.parametrize(
    ("label", "kind", "failure", "field", "reason"),
    FAILURES,
    ids=[f[0] for f in FAILURES],
)
def test_github_reads_failure_reasons(
    label: str, kind: str, failure: Failure, field: str, reason: str
) -> None:
    fake = FakeGitHub(API)
    fake.add_queued("acme/api", 1, T1, files=[("src/a.py", 3, 0)])
    fake.add_queued("acme/api", 2, T1, files=[("src/b.py", 3, 0)])
    fake.fail(kind, failure, "acme/api", 2)

    got = by_key(read_candidates(fake, plan_config(), "test-token"))
    assert set(got) == {
        ("acme/api", 1),
        ("acme/api", 2),
    }  # one failed read never aborts the run
    failed = got[("acme/api", 2)]
    assert getattr(failed.reads, field) == Unavailable(reason)
    if field == "pr":
        assert failed.event == Unavailable(reason)
    healthy = got[("acme/api", 1)]
    assert healthy.event == Event("acme/api", 1, "main", "feature")
    assert isinstance(healthy.reads.files, tuple)
    assert isinstance(healthy.reads.review, ReviewTurn)


RUN_FAILURES = [
    ("search 500", "search", Failure(status=500), None),
    ("search network", "search", Failure(raises=ConnectionError("refused")), None),
    ("viewer 502", "graphql_viewer", Failure(status=502), None),
    (
        "401 on a candidate read",
        "files",
        Failure(status=401, body=b'{"message": "Bad credentials"}'),
        1,
    ),
]


@pytest.mark.parametrize(
    ("label", "kind", "failure", "number"),
    RUN_FAILURES,
    ids=[f[0] for f in RUN_FAILURES],
)
def test_github_reads_run_failures_exit_1(
    label: str,
    kind: str,
    failure: Failure,
    number: int | None,
    live: Mapping[str, Path],
) -> None:
    fake = FakeGitHub(API)
    fake.add_queued(
        "acme/api", 1, datetime.now(UTC) - timedelta(days=1), files=[("src/a.py", 3, 0)]
    )
    fake.fail(kind, failure, "acme/api" if number else None, number)
    result = run_cli(["list"], transport=fake)
    assert not result.crash, result.crash
    assert result.code == 1
    assert len(result.err.strip().splitlines()) >= 1


# ---- I17 -----------------------------------------------------------------

ENV_CANARY = "ghp_ENVCANARY0123456789"
GH_CANARY = "gho_GHCANARY9876543210"


def fake_gh(bin_dir: Path, stdout: str, code: int = 0) -> None:
    script = bin_dir / "gh"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "auth" ] && [ "$2" = "token" ]; then\n'
        f"  printf '%s\\n' '{stdout}'\n"
        f"  exit {code}\n"
        "fi\n"
        "exit 1\n"
    )
    script.chmod(0o755)


def queued_world(api: str = API, payload_host: str | None = None) -> FakeGitHub:
    fake = FakeGitHub(api, payload_host=payload_host)
    fake.add_queued(
        "acme/api",
        412,
        datetime.now(UTC) - timedelta(days=7),
        files=[("auth/session.py", 300, 80)],
    )
    fake.add_queued(
        "acme/web",
        7,
        datetime.now(UTC) - timedelta(days=2),
        files=[("src/a.py", 10, 0)],
    )
    return fake


def assert_no_secret(secret: str, *texts: str) -> None:
    for text in texts:
        assert secret not in text


def scan_sqlite(path: Path) -> str:
    conn = sqlite3.connect(path)
    try:
        chunks = []
        for name, sql in conn.execute("SELECT name, sql FROM sqlite_master"):
            chunks.append(f"{name} {sql}")
        tables = [
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for value in row:
                    chunks.append(
                        value.decode("utf-8", "replace")
                        if isinstance(value, bytes)
                        else str(value)
                    )
        return "\n".join(chunks)
    finally:
        conn.close()


def test_auth_secret(
    live: Mapping[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    root = live["home"].parent

    # 1. Token from the env var.
    monkeypatch.setenv("GITHUB_TOKEN", ENV_CANARY)
    fake = queued_world()
    ok = run_cli(["list"], transport=fake)
    assert (ok.code, ok.crash) == (0, "")
    assert any(
        ENV_CANARY in lower_headers(r).get("authorization", "") for r in fake.requests
    )
    assert_no_secret(ENV_CANARY, ok.out, ok.err, *fake.urls())

    # 2. Forced failures with the env token.
    for kind, failure in (
        ("search", Failure(status=401, body=b'{"message": "Bad credentials"}')),
        ("search", Failure(status=500)),
        ("search", Failure(raises=ConnectionError("connection refused"))),
        ("files", Failure(raises=TimeoutError("timed out"))),
    ):
        fake = queued_world()
        fake.fail(kind, failure)
        bad = run_cli(["list"], transport=fake)
        assert_no_secret(ENV_CANARY, bad.out, bad.err, bad.crash, *fake.urls())

    # 3. Empty env token → falls back to `gh auth token`.
    monkeypatch.setenv("GITHUB_TOKEN", "")
    fake_gh(live["bin"], GH_CANARY)
    fake = queued_world()
    via_gh = run_cli(["list"], transport=fake)
    assert (via_gh.code, via_gh.crash) == (0, "")
    assert any(
        GH_CANARY in lower_headers(r).get("authorization", "") for r in fake.requests
    )
    assert_no_secret(GH_CANARY, via_gh.out, via_gh.err, *fake.urls())

    # 4. No env token and a failing gh → exit 1 with one line.
    monkeypatch.delenv("GITHUB_TOKEN")
    fake_gh(live["bin"], GH_CANARY, code=1)
    fake = queued_world()
    missing = run_cli(["list"], transport=fake)
    assert missing.crash == ""
    assert missing.code == 1
    assert len(missing.err.strip().splitlines()) == 1
    assert_no_secret(GH_CANARY, missing.out, missing.err)

    # 5. Watch state: the poller stores metadata only.
    db = root / "state.sqlite3"
    fake = queued_world()
    fake.queue_notifications(
        [fake.notification("acme/api", 412)],
        last_modified="Thu, 24 Sep 2026 12:00:00 GMT",
    )
    poller = Poller(fake, Store(db), plan_config(), ENV_CANARY)
    poller.poll_once(NOW)
    assert db.exists()
    assert_no_secret(ENV_CANARY, scan_sqlite(db), *fake.urls())

    # Nothing on disk and nothing logged holds either token.
    for path in all_files(root):
        if path.name == "gh":
            continue
        data = path.read_bytes()
        assert ENV_CANARY.encode() not in data, path
        assert GH_CANARY.encode() not in data, path
    assert_no_secret(ENV_CANARY, caplog.text)
    assert_no_secret(GH_CANARY, caplog.text)


CANARY_HOST = "https://canary-host.invalid"


def test_payload_urls_not_followed(live: Mapping[str, Path], tmp_path: Path) -> None:
    fake = queued_world(payload_host=CANARY_HOST)
    for n in range(100, 140):  # enough to page search and to carry Link headers
        fake.add_queued(
            "acme/bulk",
            n,
            datetime.now(UTC) - timedelta(days=1),
            files=[("src/x.py", 1, 0)],
        )

    listing = run_cli(["list", "--json"], transport=fake)
    assert (listing.code, listing.crash) == (0, "")
    assert json.loads(listing.out)["total"] == 42
    why = run_cli(["why", "acme/api#412"], transport=fake)
    assert (why.code, why.crash) == (0, "")
    show = run_cli(["show", "acme/api#412"], transport=fake)
    assert (show.code, show.crash) == (0, "")

    fake.queue_notifications(
        [fake.notification("acme/web", 7)],
        last_modified="Thu, 24 Sep 2026 12:00:00 GMT",
    )
    items = Poller(
        fake, Store(tmp_path / "state.sqlite3"), plan_config(), "test-token"
    ).poll_once(NOW)
    assert [(i.repo, i.number) for i in items] == [("acme/web", 7)]

    assert fake.requests
    for url in fake.urls():
        assert url.startswith(API + "/"), url
        assert "canary" not in url, url
        assert urlsplit(url).netloc == urlsplit(API).netloc
    assert any(urlsplit(u).path == "/repos/acme/web/pulls/7" for u in fake.urls())


# ---- accepted build-review findings (I17) ----------------------------------


class _RecordingServer:
    """A local HTTP server that logs each request and answers with a fixed reply."""

    def __init__(self, status: int, headers: Mapping[str, str]) -> None:
        seen: list[tuple[str, dict[str, str]]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                seen.append(
                    (self.path, {k.lower(): v for k, v in self.headers.items()})
                )
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.seen = seen
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


REDIRECT_TOKEN = "ghp_REDIRECTCANARY0123456789"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_not_followed(status: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """build review, http.py:47: a 3xx comes back as a Response; no second host is asked."""
    for var in ("http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv(var.upper(), raising=False)
    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setenv("NO_PROXY", "*")

    with _RecordingServer(200, {}) as elsewhere:
        location = {"Location": elsewhere.url + "/stolen"}
        with _RecordingServer(status, location) as origin:
            response = UrllibTransport().send(
                Request(
                    method="GET",
                    url=origin.url + "/repos/acme/api/pulls/1",
                    headers={
                        "Authorization": f"Bearer {REDIRECT_TOKEN}",
                        "Accept": "application/vnd.github+json",
                    },
                    body=None,
                )
            )

    assert response.status == status
    assert len(origin.seen) == 1
    assert origin.seen[0][0] == "/repos/acme/api/pulls/1"
    assert elsewhere.seen == []


@pytest.mark.parametrize(
    "api_url",
    [
        "http://api.github.com",
        "HTTP://api.github.com",
        "http://127.0.0.1:8080/api/v3",
        "ftp://api.github.com",
        "api.github.com",
    ],
)
def test_api_url_must_be_https(
    api_url: str, live: Mapping[str, Path], tmp_path: Path
) -> None:
    """build review, config.py:81: only an https `github.api_url` is accepted."""
    good = tmp_path / "good.toml"
    good.write_text('[github]\napi_url = "https://ghe.example.test/api/v3"\n')
    assert load_config(good).github_api_url == "https://ghe.example.test/api/v3"

    bad = tmp_path / "bad.toml"
    bad.write_text(f'[github]\napi_url = "{api_url}"\n')
    with pytest.raises(ValueError) as info:
        load_config(bad)
    assert re.search(
        r"(?<![A-Za-z0-9_.])github\.api_url(?![A-Za-z0-9_])", str(info.value)
    ), str(info.value)

    # Through the CLI: the token is never sent to the non-https base.
    write_config(live, f'[github]\napi_url = "{api_url}"\n')
    fake = queued_world()
    result = run_cli(["list"], transport=fake)
    assert result.code != 0, result.out
    assert fake.requests == []
    assert_no_secret("test-token", result.out, result.err, result.crash)
