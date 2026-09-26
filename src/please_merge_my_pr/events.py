"""Stable event and live-read value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

type CIState = Literal["passing", "failing", "pending", "none"]


@dataclass(frozen=True)
class Unavailable:
    reason: str


@dataclass(frozen=True)
class Event:
    repo: str
    number: int
    base_ref: str
    head_ref: str

    @classmethod
    def from_github_rest(cls, pr: dict[str, Any]) -> Event:
        return cls(
            repo=str(pr["base"]["repo"]["full_name"]),
            number=int(pr["number"]),
            base_ref=str(pr["base"]["ref"]),
            head_ref=str(pr["head"]["ref"]),
        )

    @classmethod
    def from_gh_archive(cls, event: dict[str, Any]) -> Event:
        pr = event["payload"]["pull_request"]
        return cls(
            repo=str(event["repo"]["name"]),
            number=int(pr["number"]),
            base_ref=str(pr["base"]["ref"]),
            head_ref=str(pr["head"]["ref"]),
        )


@dataclass(frozen=True)
class PRDetails:
    author: str
    title: str
    body: str
    labels: tuple[str, ...]
    additions: int
    deletions: int
    milestone_due: datetime | None
    created_at: datetime
    updated_at: datetime
    draft: bool

    @classmethod
    def from_github_rest(cls, pr: dict[str, Any]) -> PRDetails:
        milestone = pr.get("milestone")
        due = milestone.get("due_on") if isinstance(milestone, dict) else None
        return cls(
            author=str(pr["user"]["login"]),
            title=str(pr.get("title") or ""),
            body=str(pr.get("body") or ""),
            labels=tuple(sorted(str(label["name"]) for label in pr.get("labels", []))),
            additions=int(pr["additions"]),
            deletions=int(pr["deletions"]),
            milestone_due=_parse_time(due) if due else None,
            created_at=_parse_time(pr["created_at"]),
            updated_at=_parse_time(pr["updated_at"]),
            draft=bool(pr.get("draft", False)),
        )


@dataclass(frozen=True)
class FileChange:
    path: str
    additions: int
    deletions: int
    patch: str | None = None


@dataclass(frozen=True)
class ReviewTurn:
    requested_at: datetime | None
    by_name: bool
    as_code_owner: bool
    requested_by_user: bool


@dataclass(frozen=True)
class Reads:
    pr: PRDetails | Unavailable
    files: tuple[FileChange, ...] | Unavailable
    review: ReviewTurn | Unavailable
    ci: CIState | Unavailable
    mergeable: bool | Unavailable
    blocked_people: tuple[str, ...] | Unavailable = ()


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise TypeError("invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed.astimezone(UTC)
