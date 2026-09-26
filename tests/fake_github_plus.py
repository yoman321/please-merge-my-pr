"""FakeGitHub plus the reads and writes that plans/chat.md adds.

Every route below follows GitHub's REST docs. The Build session relies on
this contract:

- Writes (C25): `POST /repos/{o}/{r}/issues/{n}/labels`,
  `DELETE /repos/{o}/{r}/issues/{n}/labels/{name}` (name URL-encoded),
  `PUT /repos/{o}/{r}/pulls/{n}/merge`, `POST /repos/{o}/{r}/issues/{n}/comments`,
  `POST /repos/{o}/{r}/pulls/{n}/reviews`. Every write lands in `writes`.
  `fail_write(method, path, failure)` makes one write fail.
- Blocks (C24, first source): `GET /repos/{o}/{r}/issues/{n}/dependencies/blocking`
  lists the issues this PR blocks, as Issue objects with `repository_url`,
  `assignees`, and `state`. Paged like other REST lists.
- Blocks (C24, second source): `GET /repos/{o}/{r}/pulls?state=open&base=<ref>`
  lists open PRs whose base branch is `<ref>`, with `user` and `assignees`.
- Milestones (C24): the pull JSON carries `milestone.due_on` when set.
- Diffs (C26): each file in `/pulls/{n}/files` has a `patch`, except binary
  files, which have none. `GET /repos/{o}/{r}/pulls/{n}` with
  `Accept: application/vnd.github.diff` returns the unified diff text.
- `fail("blocking" | "stack", failure, repo, number)` fails one of the two
  blocks sources.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from fake_github import Failure, FakeGitHub, FakePR, iso, lower_headers

from please_merge_my_pr.github.http import Request, Response


@dataclass
class BlockedIssue:
    repo: str
    number: int
    assignees: list[str] = field(default_factory=list)
    state: str = "open"


@dataclass
class Extra:
    assignees: list[str] = field(default_factory=list)
    milestone_due: datetime | None = None
    milestone: bool = False
    patches: dict[str, str | None] = field(default_factory=dict)
    blocking: list[BlockedIssue] = field(default_factory=list)


class FakeGitHubPlus(FakeGitHub):
    def __init__(self, api_url: str, viewer: str = "me") -> None:
        super().__init__(api_url, viewer)
        self.extra: dict[tuple[str, int], Extra] = {}
        self.writes: list[Request] = []
        self.write_failures: dict[tuple[str, str], Failure] = {}

    # ---- world setup -------------------------------------------------

    def more(self, repo: str, number: int) -> Extra:
        return self.extra.setdefault((repo, number), Extra())

    def add_stacked(
        self,
        repo: str,
        number: int,
        base_ref: str,
        author: str,
        assignees: list[str] | None = None,
    ) -> FakePR:
        """An open PR outside the queue whose base branch is `base_ref`."""
        pr = self.add(
            FakePR(
                repo=repo,
                number=number,
                author=author,
                base_ref=base_ref,
                head_ref=f"stack-{number}",
                in_search=False,
            )
        )
        self.more(repo, number).assignees = list(assignees or [])
        return pr

    def fail_write(self, method: str, path: str, failure: Failure) -> None:
        self.write_failures[(method.upper(), path)] = failure

    def write_calls(self) -> list[tuple[str, str, Any]]:
        """(method, path, parsed JSON body or None) for every write, in order."""
        out = []
        for request in self.writes:
            path = urlsplit(request.url).path
            body = json.loads(request.body) if request.body else None
            out.append((request.method.upper(), path, body))
        return out

    # ---- transport ---------------------------------------------------

    def send(self, request: Request) -> Response:
        method = request.method.upper()
        parts = urlsplit(request.url)
        in_api = request.url.startswith(self.api_url + "/")
        path = parts.path[len(urlsplit(self.api_url).path) :] if in_api else ""
        if (
            in_api
            and method in {"POST", "PUT", "DELETE", "PATCH"}
            and path != "/graphql"
        ):
            self.requests.append(request)
            self.writes.append(request)
            return self._write(method, parts.path, path, request)
        if in_api and method == "GET":
            handled = self._extra_get(path, parts.query, request)
            if handled is not None:
                self.requests.append(request)
                return handled
        return super().send(request)

    # ---- reads -------------------------------------------------------

    def _extra_get(
        self, path: str, raw_query: str, request: Request
    ) -> Response | None:
        query = {k: v[-1] for k, v in parse_qs(raw_query).items()}
        m = re.fullmatch(
            r"/repos/([^/]+)/([^/]+)/issues/(\d+)/dependencies/blocking", path
        )
        if m:
            repo, number = f"{m.group(1)}/{m.group(2)}", int(m.group(3))
            if failure := self._find_failure("blocking", repo, number):
                return self._failure(failure)
            items = [self._issue_json(i) for i in self.more(repo, number).blocking]
            return self._paged(path, query, items)
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/pulls", path)
        if m:
            repo = f"{m.group(1)}/{m.group(2)}"
            base = query.get("base")
            if failure := self._find_failure("stack", repo, None):
                return self._failure(failure)
            prs = sorted(
                (
                    pr
                    for pr in self.prs.values()
                    if pr.repo == repo and (base is None or pr.base_ref == base)
                ),
                key=lambda pr: pr.number,
            )
            if query.get("state", "open") not in {"open", "all"}:
                prs = []
            return self._paged(path, query, [self._pull_json(pr) for pr in prs])
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/pulls/(\d+)", path)
        accept = lower_headers(request).get("accept", "")
        if m and "diff" in accept:
            pr = self.prs.get((f"{m.group(1)}/{m.group(2)}", int(m.group(3))))
            if pr is None:
                return self._json(404, {"message": "Not Found"})
            return self._response(
                200,
                self._diff_text(pr).encode(),
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        return None

    def _pull_json(self, pr: FakePR) -> dict[str, Any]:
        out = super()._pull_json(pr)
        extra = self.more(pr.repo, pr.number)
        out["assignees"] = [self._user(login) for login in extra.assignees]
        if extra.milestone or extra.milestone_due is not None:
            out["milestone"] = {
                "number": 1,
                "title": "v1",
                "state": "open",
                "due_on": iso(extra.milestone_due) if extra.milestone_due else None,
            }
        return out

    def _file_json(self, pr: FakePR, f: tuple[str, int, int]) -> dict[str, Any]:
        out = super()._file_json(pr, f)
        patches = self.more(pr.repo, pr.number).patches
        if f[0] in patches:
            patch = patches[f[0]]
            if patch is None:
                out.pop("patch", None)
                out["status"] = "added"
            else:
                out["patch"] = patch
        return out

    def _diff_text(self, pr: FakePR) -> str:
        chunks = []
        for f in pr.files:
            patch = self._file_json(pr, f).get("patch")
            header = f"diff --git a/{f[0]} b/{f[0]}\n"
            if patch is None:
                chunks.append(header + f"Binary files a/{f[0]} and b/{f[0]} differ\n")
            else:
                chunks.append(header + f"--- a/{f[0]}\n+++ b/{f[0]}\n{patch}\n")
        return "".join(chunks)

    def _issue_json(self, issue: BlockedIssue) -> dict[str, Any]:
        base = f"{self.payload_base}/repos/{issue.repo}"
        return {
            "id": issue.number * 131,
            "node_id": f"I_{issue.number}",
            "url": f"{base}/issues/{issue.number}",
            "repository_url": base,
            "html_url": f"{self.payload_base}/{issue.repo}/issues/{issue.number}",
            "number": issue.number,
            "state": issue.state,
            "title": "A blocked issue",
            "user": self._user("reporter"),
            "labels": [],
            "assignee": self._user(issue.assignees[0]) if issue.assignees else None,
            "assignees": [self._user(login) for login in issue.assignees],
            "comments": 0,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
            "closed_at": None,
            "body": None,
        }

    # ---- writes ------------------------------------------------------

    def _write(
        self, method: str, full_path: str, path: str, request: Request
    ) -> Response:
        if failure := self.write_failures.get((method, full_path)):
            return self._failure(failure)
        try:
            body = json.loads(request.body) if request.body else None
        except ValueError:
            return self._json(400, {"message": "Problems parsing JSON"})
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/(issues|pulls)/(\d+)/(.+)", path)
        if not m:
            return self._json(404, {"message": "Not Found"})
        repo, kind, number, rest = (
            f"{m.group(1)}/{m.group(2)}",
            m.group(3),
            int(m.group(4)),
            m.group(5),
        )
        pr = self.prs.get((repo, number))
        if pr is None:
            return self._json(404, {"message": "Not Found"})
        if kind == "issues" and rest == "labels" and method == "POST":
            for label in body["labels"]:
                if label not in pr.labels:
                    pr.labels.append(label)
            return self._json(200, [{"name": n} for n in pr.labels])
        if kind == "issues" and rest.startswith("labels/") and method == "DELETE":
            name = unquote(rest[len("labels/") :])
            if name not in pr.labels:
                return self._json(404, {"message": "Label does not exist"})
            pr.labels.remove(name)
            return self._json(200, [{"name": n} for n in pr.labels])
        if kind == "pulls" and rest == "merge" and method == "PUT":
            return self._json(
                200,
                {
                    "sha": "abc123",
                    "merged": True,
                    "message": "Pull Request successfully merged",
                },
            )
        if kind == "issues" and rest == "comments" and method == "POST":
            return self._json(201, {"id": 1, "body": body["body"]})
        if kind == "pulls" and rest == "reviews" and method == "POST":
            return self._json(200, {"id": 1, "state": "APPROVED"})
        return self._json(404, {"message": "Not Found"})
