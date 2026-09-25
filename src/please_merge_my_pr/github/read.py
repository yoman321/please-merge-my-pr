"""Read and normalize the live GitHub state for queue candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote_plus, urlsplit

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import (
    CIState,
    Event,
    FileChange,
    PRDetails,
    Reads,
    ReviewTurn,
    Unavailable,
)
from please_merge_my_pr.github.http import Request, Response, Transport


@dataclass(frozen=True)
class Candidate:
    repo: str
    number: int
    event: Event | Unavailable
    reads: Reads


class GitHubError(Exception):
    pass


class _ReadError(Exception):
    def __init__(self, reason: str, *, fatal: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fatal = fatal


def read_candidates(
    transport: Transport, config: Config, token: str
) -> list[Candidate]:
    base = config.github_api_url.rstrip("/")
    headers = _headers(token)
    try:
        viewer_data = _graphql(transport, base, headers, "query { viewer { login } }")
        viewer = str(viewer_data["viewer"]["login"])
        if not viewer:
            raise KeyError("viewer")
        keys = _search(transport, base, headers, config.repos)
    except (_ReadError, KeyError, TypeError, ValueError) as exc:
        raise GitHubError("could not discover GitHub review requests") from exc

    return [
        _read_one(transport, base, headers, repo, number, viewer)
        for repo, number in keys
    ]


def read_candidate(
    transport: Transport,
    config: Config,
    token: str,
    repo: str,
    number: int,
) -> Candidate:
    """Read one known PR. Used by notification polling."""
    base = config.github_api_url.rstrip("/")
    headers = _headers(token)
    try:
        viewer_data = _graphql(transport, base, headers, "query { viewer { login } }")
        viewer = str(viewer_data["viewer"]["login"])
    except (_ReadError, KeyError, TypeError, ValueError) as exc:
        raise GitHubError("could not identify the GitHub viewer") from exc
    return _read_one(transport, base, headers, repo, number, viewer)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "please-merge-my-pr/0.1",
    }


def _reason(response: Response) -> str:
    lower = {key.lower(): value for key, value in response.headers.items()}
    if response.status == 401:
        return "unauthorized"
    if response.status == 403:
        return (
            "rate_limited" if lower.get("x-ratelimit-remaining") == "0" else "forbidden"
        )
    if response.status == 404:
        return "not_found"
    if response.status == 429:
        return "rate_limited"
    if response.status >= 500:
        return "server_error"
    return "invalid_response"


def _json_request(
    transport: Transport,
    request: Request,
    *,
    expected: type,
) -> Any:
    try:
        response = transport.send(request)
    except TimeoutError:
        raise _ReadError("timeout") from None
    except OSError:
        raise _ReadError("network_error") from None
    if response.status != 200:
        reason = _reason(response)
        raise _ReadError(reason, fatal=response.status == 401)
    try:
        value = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _ReadError("invalid_response") from None
    if not isinstance(value, expected):
        raise _ReadError("invalid_response")
    return value


def _get(
    transport: Transport,
    url: str,
    headers: dict[str, str],
    expected: type,
) -> Any:
    return _json_request(
        transport,
        Request("GET", url, headers, None),
        expected=expected,
    )


def _graphql(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    query: str,
    variables: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = json.dumps(
        {"query": query, "variables": variables or {}}, sort_keys=True
    ).encode()
    payload = _json_request(
        transport,
        Request("POST", f"{base}/graphql", headers, body),
        expected=dict,
    )
    if payload.get("errors") or not isinstance(payload.get("data"), dict):
        raise _ReadError("invalid_response")
    return payload["data"]


def _search(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    repos: tuple[str, ...],
) -> list[tuple[str, int]]:
    query = "is:pr is:open review-requested:@me"
    if repos:
        query += " " + " ".join(f"repo:{repo}" for repo in repos)
    keys: list[tuple[str, int]] = []
    page = 1
    while True:
        url = f"{base}/search/issues?q={quote_plus(query)}&per_page=100&page={page}"
        payload = _get(transport, url, headers, dict)
        items = payload.get("items")
        total = payload.get("total_count")
        if not isinstance(items, list) or not isinstance(total, int):
            raise _ReadError("invalid_response")
        for item in items:
            try:
                path = urlsplit(str(item["repository_url"])).path.rstrip("/")
                marker = "/repos/"
                repo = path[path.index(marker) + len(marker) :]
                owner, name = repo.split("/", 1)
                if not owner or not name:
                    raise ValueError
                keys.append((repo, int(item["number"])))
            except (KeyError, TypeError, ValueError):
                raise _ReadError("invalid_response") from None
        if len(keys) >= total or not items:
            return keys
        page += 1


def _rest_pages(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    path: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        chunk = _get(
            transport,
            f"{base}{path}?per_page=100&page={page}",
            headers,
            list,
        )
        if not all(isinstance(item, dict) for item in chunk):
            raise _ReadError("invalid_response")
        items.extend(chunk)
        if len(chunk) < 100:
            return items
        page += 1


def _read_one(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    repo: str,
    number: int,
    viewer: str,
) -> Candidate:
    pull_path = f"/repos/{repo}/pulls/{number}"
    try:
        raw_pr = _get(transport, f"{base}{pull_path}", headers, dict)
        event: Event | Unavailable = Event.from_github_rest(raw_pr)
        pr: PRDetails | Unavailable = PRDetails.from_github_rest(raw_pr)
    except _ReadError as exc:
        if exc.fatal:
            raise GitHubError("GitHub credentials were rejected") from exc
        missing = Unavailable(exc.reason)
        reads = Reads(missing, missing, missing, missing, missing)
        return Candidate(repo, number, missing, reads)
    except (KeyError, TypeError, ValueError):
        missing = Unavailable("invalid_response")
        reads = Reads(missing, missing, missing, missing, missing)
        return Candidate(repo, number, missing, reads)

    files = _read_files(transport, base, headers, repo, number)
    review = _read_review(transport, base, headers, repo, number, viewer)
    ci = _read_ci(transport, base, headers, repo, number)
    mergeable: bool | Unavailable = (
        Unavailable("computing")
        if raw_pr.get("mergeable") is None
        else bool(raw_pr["mergeable"])
    )
    return Candidate(repo, number, event, Reads(pr, files, review, ci, mergeable))


def _read_files(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    repo: str,
    number: int,
) -> tuple[FileChange, ...] | Unavailable:
    try:
        raw = _rest_pages(
            transport, base, headers, f"/repos/{repo}/pulls/{number}/files"
        )
        return tuple(
            sorted(
                (
                    FileChange(
                        str(item["filename"]),
                        int(item["additions"]),
                        int(item["deletions"]),
                    )
                    for item in raw
                ),
                key=lambda item: item.path,
            )
        )
    except _ReadError as exc:
        if exc.fatal:
            raise GitHubError("GitHub credentials were rejected") from exc
        return Unavailable(exc.reason)
    except (KeyError, TypeError, ValueError):
        return Unavailable("invalid_response")


def _read_review(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    repo: str,
    number: int,
    viewer: str,
) -> ReviewTurn | Unavailable:
    owner, name = repo.split("/", 1)
    nodes: list[dict[str, Any]] = []
    cursor: str | None = None
    query = """
      query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) {
            reviewRequests(first: 100, after: $cursor) {
              nodes { asCodeOwner requestedReviewer { __typename ... on User { login } } }
              pageInfo { hasNextPage endCursor }
            }
          }
        }
      }
    """
    try:
        while True:
            data = _graphql(
                transport,
                base,
                headers,
                query,
                {"owner": owner, "name": name, "number": number, "cursor": cursor},
            )
            connection = data["repository"]["pullRequest"]["reviewRequests"]
            nodes.extend(connection["nodes"])
            page = connection["pageInfo"]
            if not page["hasNextPage"]:
                break
            cursor = str(page["endCursor"])
    except _ReadError as exc:
        if exc.fatal:
            raise GitHubError("GitHub credentials were rejected") from exc
        return Unavailable(exc.reason)
    except (KeyError, TypeError, ValueError):
        return Unavailable("invalid_response")

    matches = [
        node
        for node in nodes
        if isinstance(node, dict)
        and isinstance(node.get("requestedReviewer"), dict)
        and node["requestedReviewer"].get("__typename") == "User"
        and node["requestedReviewer"].get("login") == viewer
    ]
    if not matches:
        return ReviewTurn(None, False, False, False)
    as_code_owner = bool(matches[-1].get("asCodeOwner"))
    try:
        timeline = _rest_pages(
            transport, base, headers, f"/repos/{repo}/issues/{number}/timeline"
        )
    except _ReadError as exc:
        if exc.fatal:
            raise GitHubError("GitHub credentials were rejected") from exc
        return Unavailable(exc.reason)
    matching_events = [
        item
        for item in timeline
        if item.get("event") == "review_requested"
        and isinstance(item.get("requested_reviewer"), dict)
        and item["requested_reviewer"].get("login") == viewer
    ]
    if not matching_events:
        return Unavailable("unmatched")
    try:
        latest = max(matching_events, key=lambda item: _time(item["created_at"]))
        requester = latest.get("review_requester") or latest.get("actor") or {}
        return ReviewTurn(
            requested_at=_time(latest["created_at"]),
            by_name=True,
            as_code_owner=as_code_owner,
            requested_by_user=requester.get("type") == "User",
        )
    except (KeyError, TypeError, ValueError):
        return Unavailable("invalid_response")


def _read_ci(
    transport: Transport,
    base: str,
    headers: dict[str, str],
    repo: str,
    number: int,
) -> CIState | Unavailable:
    owner, name = repo.split("/", 1)
    query = """
      query($owner: String!, $name: String!, $number: Int!) {
        repository(owner: $owner, name: $name) {
          pullRequest(number: $number) { statusCheckRollup { state } }
        }
      }
    """
    try:
        data = _graphql(
            transport,
            base,
            headers,
            query,
            {"owner": owner, "name": name, "number": number},
        )
        rollup = data["repository"]["pullRequest"]["statusCheckRollup"]
        if rollup is None:
            return "none"
        state = str(rollup["state"]).upper()
        if state in {"SUCCESS", "EXPECTED"}:
            return "passing"
        if state in {"PENDING"}:
            return "pending"
        return "failing"
    except _ReadError as exc:
        if exc.fatal:
            raise GitHubError("GitHub credentials were rejected") from exc
        return Unavailable(exc.reason)
    except (KeyError, TypeError, ValueError):
        return Unavailable("invalid_response")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError
    return parsed.astimezone(UTC)
