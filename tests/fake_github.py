"""An in-memory GitHub that speaks the Transport protocol.

Response shapes follow GitHub's docs (REST issue timeline events, REST
notifications, the public GraphQL schema) and the real REST PR fixture.

Contract the fake relies on, so the Build session can read it:

- REST lists honor `per_page` (default 30, max 100) and `page`, and send a
  `Link` header whose URLs use the payload host.
- GraphQL answers a superset: every response carries `viewer`, `search`, and,
  when the request names one PR, `repository.pullRequest` with
  `reviewRequests`, `statusCheckRollup`, and `commits(last: 1)`. The PR is
  found from the repo and number in the variables or query literals. Pages
  are 100 nodes; a cursor from `endCursor` anywhere in the request selects the
  next page. Aliases and multi-PR batching are not supported.
- Timeouts raise TimeoutError; network failures raise ConnectionError.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from please_merge_my_pr.github.http import Request, Response

GRAPHQL_PAGE = 100


class Headers(Mapping[str, str]):
    """Case-insensitive, like urllib's HTTPMessage."""

    def __init__(self, items: Mapping[str, str] | None = None) -> None:
        self._items: dict[str, tuple[str, str]] = {}
        for key, value in (items or {}).items():
            self._items[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> str:
        return self._items[key.lower()][1]

    def __iter__(self) -> Iterator[str]:
        return (original for original, _ in self._items.values())

    def __len__(self) -> int:
        return len(self._items)


def iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_date(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")


def lower_headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


@dataclass
class Failure:
    """What the fake sends instead of a normal answer."""

    status: int = 500
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b'{"message": "fake failure"}'
    raises: BaseException | None = None


@dataclass
class ReviewRequest:
    kind: str  # "User", "Team", or "Bot"
    login: str
    as_code_owner: bool = False


@dataclass
class TimelineEvent:
    event: str
    created_at: datetime
    reviewer: str | None = None
    team: str | None = None
    requester: str = "bob"
    requester_type: str = "User"


@dataclass
class FakePR:
    repo: str
    number: int
    author: str = "alice"
    title: str = "Tidy the session code"
    body: str = "Plain description."
    base_ref: str = "main"
    head_ref: str = "feature"
    draft: bool = False
    labels: list[str] = field(default_factory=list)
    files: list[tuple[str, int, int]] = field(default_factory=list)
    additions: int | None = None
    deletions: int | None = None
    mergeable: bool | None = True
    rollup: str | None = "SUCCESS"
    review_requests: list[ReviewRequest] = field(default_factory=list)
    timeline: list[TimelineEvent] = field(default_factory=list)
    in_search: bool = True
    created_at: datetime = datetime(2026, 9, 1, tzinfo=UTC)

    @property
    def owner(self) -> str:
        return self.repo.split("/")[0]

    @property
    def name(self) -> str:
        return self.repo.split("/")[1]


class FakeGitHub:
    def __init__(
        self,
        api_url: str,
        viewer: str = "me",
        payload_host: str | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.viewer = viewer
        self.payload_base = (payload_host or self.api_url).rstrip("/")
        self.prs: dict[tuple[str, int], FakePR] = {}
        self.requests: list[Request] = []
        self.failures: dict[tuple[Any, ...], Failure] = {}
        self.notification_script: deque[Callable[[], Response]] = deque()
        self.fail_everything: Failure | None = None

    # ---- world setup -------------------------------------------------

    def add(self, pr: FakePR) -> FakePR:
        self.prs[(pr.repo, pr.number)] = pr
        return pr

    def add_queued(
        self,
        repo: str,
        number: int,
        requested_at: datetime,
        files: list[tuple[str, int, int]] | None = None,
        **kwargs: Any,
    ) -> FakePR:
        """A PR where the viewer has a by-name request from a user."""
        return self.add(
            FakePR(
                repo=repo,
                number=number,
                files=files if files is not None else [],
                review_requests=[ReviewRequest("User", self.viewer)],
                timeline=[
                    TimelineEvent(
                        "review_requested", requested_at, reviewer=self.viewer
                    )
                ],
                **kwargs,
            )
        )

    def fail(
        self,
        kind: str,
        failure: Failure,
        repo: str | None = None,
        number: int | None = None,
    ) -> None:
        """kind: search, pull, files, timeline, notifications, graphql_viewer, graphql_review, graphql_ci."""
        self.failures[(kind, repo, number)] = failure

    def queue_notifications(
        self,
        items: list[dict[str, Any]] | None,
        *,
        status: int = 200,
        last_modified: str | None = None,
        etag: str | None = None,
        poll_interval: int = 60,
    ) -> None:
        headers = {"X-Poll-Interval": str(poll_interval)}
        if last_modified is not None:
            headers["Last-Modified"] = last_modified
        if etag is not None:
            headers["ETag"] = etag
        body = b"" if status == 304 else json.dumps(items or []).encode()
        self.notification_script.append(lambda: self._response(status, body, headers))

    def notification(
        self,
        repo: str,
        number: int,
        reason: str = "review_requested",
        kind: str = "PullRequest",
    ) -> dict[str, Any]:
        pr = self.prs.get((repo, number))
        segment = "pulls" if kind == "PullRequest" else "issues"
        return {
            "id": f"{abs(hash((repo, number, reason))) % 10**9}",
            "unread": True,
            "reason": reason,
            "updated_at": "2026-09-24T12:00:00Z",
            "last_read_at": None,
            "subject": {
                "title": pr.title if pr else "An issue",
                "url": f"{self.payload_base}/repos/{repo}/{segment}/{number}",
                "latest_comment_url": f"{self.payload_base}/repos/{repo}/issues/comments/1",
                "type": kind,
            },
            "repository": {
                "id": 1,
                "name": repo.split("/")[1],
                "full_name": repo,
                "private": False,
                "owner": self._user(repo.split("/")[0], "Organization"),
                "url": f"{self.payload_base}/repos/{repo}",
                "html_url": f"{self.payload_base}/{repo}",
            },
            "url": f"{self.payload_base}/notifications/threads/1",
            "subscription_url": f"{self.payload_base}/notifications/threads/1/subscription",
        }

    # ---- helpers for tests -------------------------------------------

    def urls(self) -> list[str]:
        return [r.url for r in self.requests]

    def notification_requests(self) -> list[Request]:
        return [
            r for r in self.requests if urlsplit(r.url).path.endswith("/notifications")
        ]

    # ---- transport ---------------------------------------------------

    def send(self, request: Request) -> Response:
        self.requests.append(request)
        if self.fail_everything is not None:
            return self._failure(self.fail_everything)
        if not request.url.startswith(self.api_url + "/"):
            return self._json(404, {"message": "Not Found"})
        parts = urlsplit(request.url)
        path = parts.path[len(urlsplit(self.api_url).path) :]
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}

        if path == "/graphql" and request.method.upper() == "POST":
            return self._graphql(request)
        if request.method.upper() != "GET":
            return self._json(404, {"message": "Not Found"})
        if path == "/search/issues":
            if failure := self._find_failure("search"):
                return self._failure(failure)
            return self._search_rest(query)
        if path == "/notifications":
            if failure := self._find_failure("notifications"):
                return self._failure(failure)
            if not self.notification_script:
                return self._response(200, b"[]", {"X-Poll-Interval": "60"})
            return self.notification_script.popleft()()
        m = re.fullmatch(
            r"/repos/([^/]+)/([^/]+)/(pulls|issues)/(\d+)(/files|/timeline)?", path
        )
        if m:
            repo, number = f"{m.group(1)}/{m.group(2)}", int(m.group(4))
            pr = self.prs.get((repo, number))
            kind = {None: "pull", "/files": "files", "/timeline": "timeline"}[
                m.group(5)
            ]
            if m.group(3) == "issues" and kind != "timeline":
                return self._json(404, {"message": "Not Found"})
            if m.group(3) == "pulls" and kind == "timeline":
                return self._json(404, {"message": "Not Found"})
            if failure := self._find_failure(kind, repo, number):
                return self._failure(failure)
            if pr is None:
                return self._json(404, {"message": "Not Found"})
            if kind == "pull":
                return self._json(200, self._pull_json(pr))
            if kind == "files":
                return self._paged(
                    path, query, [self._file_json(pr, f) for f in pr.files]
                )
            return self._paged(
                path,
                query,
                [self._timeline_json(pr, i, e) for i, e in enumerate(pr.timeline)],
            )
        return self._json(404, {"message": "Not Found"})

    # ---- internals ---------------------------------------------------

    def _find_failure(
        self, kind: str, repo: str | None = None, number: int | None = None
    ) -> Failure | None:
        return self.failures.get((kind, repo, number)) or self.failures.get(
            (kind, None, None)
        )

    def _response(
        self, status: int, body: bytes, headers: Mapping[str, str] | None = None
    ) -> Response:
        base = {
            "Content-Type": "application/json; charset=utf-8",
            "X-RateLimit-Limit": "5000",
            "X-RateLimit-Remaining": "4999",
        }
        base.update(headers or {})
        return Response(status=status, headers=Headers(base), body=body)

    def _json(
        self, status: int, payload: Any, headers: Mapping[str, str] | None = None
    ) -> Response:
        return self._response(status, json.dumps(payload).encode(), headers)

    def _failure(self, failure: Failure) -> Response:
        if failure.raises is not None:
            raise failure.raises
        return self._response(failure.status, failure.body, failure.headers)

    def _paged(self, path: str, query: Mapping[str, str], items: list[Any]) -> Response:
        per_page = min(int(query.get("per_page", "30")), 100)
        page = int(query.get("page", "1"))
        start = (page - 1) * per_page
        chunk = items[start : start + per_page]
        last = max(1, -(-len(items) // per_page))
        kept = {k: v for k, v in query.items() if k not in ("per_page", "page")}

        def link(n: int, rel: str) -> str:
            params = urlencode({**kept, "per_page": per_page, "page": n})
            return f'<{self.payload_base}{path}?{params}>; rel="{rel}"'

        links = [link(page + 1, "next"), link(last, "last")] if page < last else []
        headers = {"Link": ", ".join(links)} if links else {}
        return self._json(200, chunk, headers)

    def _user(self, login: str, kind: str = "User") -> dict[str, Any]:
        return {
            "login": login,
            "id": abs(hash(login)) % 10**8,
            "node_id": f"U_{login}",
            "type": kind,
            "site_admin": False,
            "url": f"{self.payload_base}/users/{login}",
            "html_url": f"{self.payload_base}/{login}",
            "avatar_url": f"{self.payload_base}/avatars/{login}",
        }

    def _repo_json(self, pr: FakePR) -> dict[str, Any]:
        return {
            "id": abs(hash(pr.repo)) % 10**8,
            "name": pr.name,
            "full_name": pr.repo,
            "private": False,
            "owner": self._user(pr.owner, "Organization"),
            "url": f"{self.payload_base}/repos/{pr.repo}",
            "html_url": f"{self.payload_base}/{pr.repo}",
        }

    def _pull_json(self, pr: FakePR) -> dict[str, Any]:
        additions = (
            pr.additions if pr.additions is not None else sum(f[1] for f in pr.files)
        )
        deletions = (
            pr.deletions if pr.deletions is not None else sum(f[2] for f in pr.files)
        )
        base = f"{self.payload_base}/repos/{pr.repo}"
        return {
            "url": f"{base}/pulls/{pr.number}",
            "id": pr.number * 7919,
            "node_id": f"PR_{pr.number}",
            "html_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}",
            "diff_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}.diff",
            "patch_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}.patch",
            "issue_url": f"{base}/issues/{pr.number}",
            "commits_url": f"{base}/pulls/{pr.number}/commits",
            "review_comments_url": f"{base}/pulls/{pr.number}/comments",
            "comments_url": f"{base}/issues/{pr.number}/comments",
            "statuses_url": f"{base}/statuses/abc123",
            "number": pr.number,
            "state": "open",
            "locked": False,
            "title": pr.title,
            "user": self._user(pr.author),
            "body": pr.body,
            "labels": [
                {
                    "id": i,
                    "name": name,
                    "color": "ededed",
                    "url": f"{base}/labels/{name}",
                }
                for i, name in enumerate(pr.labels)
            ],
            "milestone": None,
            "created_at": iso(pr.created_at),
            "updated_at": iso(pr.created_at),
            "closed_at": None,
            "merged_at": None,
            "draft": pr.draft,
            "head": {
                "label": f"{pr.owner}:{pr.head_ref}",
                "ref": pr.head_ref,
                "sha": "abc123",
                "user": self._user(pr.author),
                "repo": self._repo_json(pr),
            },
            "base": {
                "label": f"{pr.owner}:{pr.base_ref}",
                "ref": pr.base_ref,
                "sha": "def456",
                "user": self._user(pr.owner, "Organization"),
                "repo": self._repo_json(pr),
            },
            "requested_reviewers": [
                self._user(r.login) for r in pr.review_requests if r.kind == "User"
            ],
            "requested_teams": [],
            "_links": {"self": {"href": f"{base}/pulls/{pr.number}"}},
            "author_association": "MEMBER",
            "merged": False,
            "mergeable": pr.mergeable,
            "mergeable_state": "clean" if pr.mergeable else "unknown",
            "comments": 0,
            "review_comments": 0,
            "commits": 1,
            "additions": additions,
            "deletions": deletions,
            "changed_files": len(pr.files),
        }

    def _file_json(self, pr: FakePR, f: tuple[str, int, int]) -> dict[str, Any]:
        path, additions, deletions = f
        return {
            "sha": "0" * 40,
            "filename": path,
            "status": "modified",
            "additions": additions,
            "deletions": deletions,
            "changes": additions + deletions,
            "blob_url": f"{self.payload_base}/{pr.repo}/blob/abc123/{path}",
            "raw_url": f"{self.payload_base}/{pr.repo}/raw/abc123/{path}",
            "contents_url": f"{self.payload_base}/repos/{pr.repo}/contents/{path}?ref=abc123",
            "patch": f"@@ -1 +1 @@\n-{path}\n+{path}",
        }

    def _timeline_json(
        self, pr: FakePR, index: int, e: TimelineEvent
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": index + 1,
            "node_id": f"E_{pr.number}_{index}",
            "url": f"{self.payload_base}/repos/{pr.repo}/issues/events/{index + 1}",
            "actor": self._user(e.requester, e.requester_type),
            "event": e.event,
            "commit_id": None,
            "commit_url": None,
            "created_at": iso(e.created_at),
        }
        if e.event in ("review_requested", "review_request_removed"):
            out["review_requester"] = self._user(e.requester, e.requester_type)
            if e.team is not None:
                out["requested_team"] = {
                    "name": e.team,
                    "slug": e.team,
                    "url": f"{self.payload_base}/orgs/{pr.owner}/teams/{e.team}",
                }
            else:
                out["requested_reviewer"] = self._user(e.reviewer or "")
        elif e.event == "labeled":
            out["label"] = {"name": "filler", "color": "ededed"}
        return out

    def _search_items(self) -> list[FakePR]:
        return sorted(
            (pr for pr in self.prs.values() if pr.in_search),
            key=lambda p: (p.repo, p.number),
        )

    def _search_rest(self, query: Mapping[str, str]) -> Response:
        prs = self._search_items()
        items = [
            {
                "url": f"{self.payload_base}/repos/{pr.repo}/issues/{pr.number}",
                "repository_url": f"{self.payload_base}/repos/{pr.repo}",
                "html_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}",
                "number": pr.number,
                "state": "open",
                "title": pr.title,
                "user": self._user(pr.author),
                "draft": pr.draft,
                "pull_request": {
                    "url": f"{self.payload_base}/repos/{pr.repo}/pulls/{pr.number}",
                    "html_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}",
                    "diff_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}.diff",
                    "patch_url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}.patch",
                },
            }
            for pr in prs
        ]
        response = self._paged("/search/issues", query, items)
        page = json.loads(response.body)
        wrapped = {
            "total_count": len(items),
            "incomplete_results": False,
            "items": page,
        }
        return self._response(200, json.dumps(wrapped).encode(), dict(response.headers))

    # ---- GraphQL -----------------------------------------------------

    def _graphql(self, request: Request) -> Response:
        raw = (request.body or b"").decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except ValueError:
            return self._json(400, {"message": "Problems parsing JSON"})
        query = str(payload.get("query", ""))
        variables = payload.get("variables") or {}

        wants = {
            "graphql_viewer": "viewer" in query,
            "graphql_review": "reviewRequests" in query,
            "graphql_ci": "statusCheckRollup" in query,
            "search": re.search(r"\bsearch\s*\(", query) is not None,
        }
        pr = self._identify(query, variables)
        for kind, wanted in wants.items():
            if not wanted:
                continue
            failure = (
                self._find_failure(kind, pr.repo, pr.number)
                if pr
                else self._find_failure(kind)
            )
            if failure:
                return self._failure(failure)

        data: dict[str, Any] = {"viewer": {"login": self.viewer, "__typename": "User"}}
        data["search"] = self._search_graphql(raw)
        if wants["graphql_review"] or wants["graphql_ci"]:
            if pr is None:
                return self._json(
                    200,
                    {
                        "data": None,
                        "errors": [{"message": "fake: could not identify one PR"}],
                    },
                )
            data["repository"] = {
                "nameWithOwner": pr.repo,
                "name": pr.name,
                "owner": {"login": pr.owner},
                "pullRequest": self._pr_graphql(pr, raw),
            }
        return self._json(200, {"data": data})

    def _identify(self, query: str, variables: Any) -> FakePR | None:
        strings: set[str] = set(re.findall(r'"([^"\\]*)"', query))
        numbered: set[int] = {int(n) for n in re.findall(r"number\s*:\s*(\d+)", query)}
        ints: set[int] = set(numbered)

        def walk(v: Any, key: str = "") -> None:
            if isinstance(v, bool):
                return
            if isinstance(v, str):
                strings.add(v)
            elif isinstance(v, int):
                ints.add(v)
                if re.search(r"num|pr|pull", key, re.IGNORECASE):
                    numbered.add(v)
            elif isinstance(v, dict):
                for k, x in v.items():
                    walk(x, str(k))
            elif isinstance(v, list):
                for x in v:
                    walk(x, key)

        walk(variables)
        for pool in (numbered, ints):
            matches = [
                pr
                for pr in self.prs.values()
                if pr.number in pool
                and (pr.repo in strings or (pr.owner in strings and pr.name in strings))
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    @staticmethod
    def _page_start(raw: str, prefix: str) -> int:
        found = [int(n) for n in re.findall(prefix + r":(\d+)", raw)]
        return max(found) if found else 0

    def _connection(self, nodes: list[Any], start: int, prefix: str) -> dict[str, Any]:
        chunk = nodes[start : start + GRAPHQL_PAGE]
        end = start + len(chunk)
        return {
            "totalCount": len(nodes),
            "nodes": chunk,
            "edges": [
                {"cursor": f"{prefix}:{start + i + 1}", "node": n}
                for i, n in enumerate(chunk)
            ],
            "pageInfo": {
                "hasNextPage": end < len(nodes),
                "hasPreviousPage": start > 0,
                "startCursor": f"{prefix}:{start + 1}" if chunk else None,
                "endCursor": f"{prefix}:{end}" if chunk else None,
            },
        }

    def _search_graphql(self, raw: str) -> dict[str, Any]:
        nodes = [
            {
                "__typename": "PullRequest",
                "number": pr.number,
                "url": f"{self.payload_base}/{pr.repo}/pull/{pr.number}",
                "repository": {
                    "nameWithOwner": pr.repo,
                    "name": pr.name,
                    "owner": {"login": pr.owner},
                },
            }
            for pr in self._search_items()
        ]
        conn = self._connection(nodes, self._page_start(raw, "srch"), "srch")
        conn["issueCount"] = len(nodes)
        return conn

    def _pr_graphql(self, pr: FakePR, raw: str) -> dict[str, Any]:
        nodes = []
        for r in pr.review_requests:
            reviewer: dict[str, Any] = {"__typename": r.kind}
            if r.kind == "Team":
                reviewer.update(
                    slug=r.login, name=r.login, combinedSlug=f"{pr.owner}/{r.login}"
                )
            else:
                reviewer.update(login=r.login)
            nodes.append(
                {"asCodeOwner": r.as_code_owner, "requestedReviewer": reviewer}
            )
        prefix = f"rr{pr.number}"
        rollup = None if pr.rollup is None else {"state": pr.rollup}
        return {
            "number": pr.number,
            "isDraft": pr.draft,
            "reviewRequests": self._connection(
                nodes, self._page_start(raw, prefix), prefix
            ),
            "statusCheckRollup": rollup,
            "commits": {
                "totalCount": 1,
                "nodes": [{"commit": {"oid": "abc123", "statusCheckRollup": rollup}}],
            },
        }
