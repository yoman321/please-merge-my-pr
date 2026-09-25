"""Load the packaged, offline demonstration world."""

from __future__ import annotations

import importlib.resources
import json
from datetime import UTC, datetime
from typing import Any

from please_merge_my_pr.events import (
    Event,
    FileChange,
    PRDetails,
    Reads,
    ReviewTurn,
    Unavailable,
)
from please_merge_my_pr.github.read import Candidate


def load_demo() -> list[Candidate]:
    resource = importlib.resources.files("please_merge_my_pr").joinpath(
        "demo/demo.json"
    )
    raw = json.loads(resource.read_text())
    return [_candidate(item) for item in raw["candidates"]]


def _candidate(item: dict[str, Any]) -> Candidate:
    event = Event(
        repo=str(item["repo"]),
        number=int(item["number"]),
        base_ref=str(item["base_ref"]),
        head_ref=str(item["head_ref"]),
    )
    created = datetime(2026, 9, 1, tzinfo=UTC)
    pr = PRDetails(
        author=str(item["author"]),
        title=str(item["title"]),
        body=str(item["body"]),
        labels=(),
        additions=int(item["additions"]),
        deletions=int(item["deletions"]),
        milestone_due=None,
        created_at=created,
        updated_at=created,
        draft=bool(item["draft"]),
    )
    files = tuple(
        sorted(
            (
                FileChange(str(path), int(additions), int(deletions))
                for path, additions, deletions in item["files"]
            ),
            key=lambda change: change.path,
        )
    )
    if reason := item.get("review_unavailable"):
        review: ReviewTurn | Unavailable = Unavailable(str(reason))
    else:
        requested = item.get("requested_at")
        review = ReviewTurn(
            requested_at=_time(requested) if requested else None,
            by_name=bool(item["by_name"]),
            as_code_owner=bool(item["as_code_owner"]),
            requested_by_user=bool(item["requested_by_user"]),
        )
    reads = Reads(
        pr=pr,
        files=files,
        review=review,
        ci=item["ci"],
        mergeable=bool(item["mergeable"]),
    )
    return Candidate(event.repo, event.number, event, reads)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
