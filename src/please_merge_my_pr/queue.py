"""Queue entry decision."""

from __future__ import annotations

from dataclasses import dataclass

from please_merge_my_pr.events import Event, Reads, Unavailable


@dataclass(frozen=True)
class In:
    pass


@dataclass(frozen=True)
class Out:
    reason: str


@dataclass(frozen=True)
class Unknown:
    reason: str


def eligible(event: Event, reads: Reads) -> In | Out | Unknown:
    del event
    if isinstance(reads.pr, Unavailable):
        return Unknown(reads.pr.reason)
    if isinstance(reads.review, Unavailable):
        return Unknown(reads.review.reason)
    if reads.pr.draft:
        return Out("draft")
    if not reads.review.by_name or reads.review.requested_at is None:
        return Out("not requested by name")
    if reads.review.as_code_owner:
        return Out("code-owner request")
    if not reads.review.requested_by_user:
        return Out("requested by bot")
    return In()
