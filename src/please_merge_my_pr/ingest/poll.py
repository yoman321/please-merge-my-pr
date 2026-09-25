"""Conditional notification polling and queue-event emission."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, ReviewTurn
from please_merge_my_pr.github.http import Request, Transport
from please_merge_my_pr.github.read import GitHubError, read_candidate
from please_merge_my_pr.queue import In, eligible
from please_merge_my_pr.scoring import score
from please_merge_my_pr.store import Store


@dataclass(frozen=True)
class WatchItem:
    repo: str
    number: int
    score: int
    reason: str


class Poller:
    def __init__(
        self, transport: Transport, store: Store, config: Config, token: str
    ) -> None:
        self.transport = transport
        self.store = store
        self.config = config
        self.token = token

    def poll_once(self, now: datetime) -> list[WatchItem]:
        key = "notifications"
        state = self.store.poll_state(key)
        if state is not None:
            last_modified, etag, interval, last_poll_raw = state
            last_poll = datetime.fromisoformat(last_poll_raw).astimezone(UTC)
            if (now - last_poll).total_seconds() < interval:
                return []
        else:
            last_modified, etag, interval = None, None, 60

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "please-merge-my-pr/0.1",
        }
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        if etag:
            headers["If-None-Match"] = etag
        response = self.transport.send(
            Request(
                "GET",
                f"{self.config.github_api_url.rstrip('/')}/notifications",
                headers,
                None,
            )
        )
        response_headers = {
            key.lower(): value for key, value in response.headers.items()
        }
        next_modified = response_headers.get("last-modified", last_modified)
        next_etag = response_headers.get("etag", etag)
        try:
            next_interval = int(response_headers.get("x-poll-interval", interval))
        except ValueError:
            next_interval = interval
        self.store.save_poll_state(
            key,
            next_modified,
            next_etag,
            max(1, next_interval),
            now.astimezone(UTC).isoformat(),
        )
        if response.status == 304:
            return []
        if response.status != 200:
            return []
        try:
            notifications = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return []
        if not isinstance(notifications, list):
            return []

        emitted = []
        for item in notifications:
            key_pair = _notification_key(item)
            if key_pair is None:
                continue
            repo, number = key_pair
            try:
                candidate = read_candidate(
                    self.transport, self.config, self.token, repo, number
                )
            except GitHubError:
                continue
            if not isinstance(candidate.event, Event):
                continue
            if not isinstance(eligible(candidate.event, candidate.reads), In):
                continue
            review = candidate.reads.review
            if not isinstance(review, ReviewTurn) or review.requested_at is None:
                continue
            requested_at = review.requested_at.astimezone(UTC).isoformat()
            if self.store.has_seen(repo, number, requested_at):
                continue
            scored = score(
                candidate.event,
                candidate.reads,
                self.config.weights,
                self.config,
                now,
            )
            emitted.append(WatchItem(repo, number, scored.score, scored.reason))
            self.store.mark_seen(repo, number, requested_at)
        return emitted


def _notification_key(item: Any) -> tuple[str, int] | None:
    if not isinstance(item, dict) or item.get("reason") != "review_requested":
        return None
    subject = item.get("subject")
    repository = item.get("repository")
    if not isinstance(subject, dict) or subject.get("type") != "PullRequest":
        return None
    if not isinstance(repository, dict) or not isinstance(
        repository.get("full_name"), str
    ):
        return None
    try:
        number = int(urlsplit(str(subject["url"])).path.rstrip("/").rsplit("/", 1)[1])
    except (KeyError, TypeError, ValueError):
        return None
    return repository["full_name"], number
