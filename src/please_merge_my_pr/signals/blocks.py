"""People blocked by this change."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, now
    if isinstance(reads.blocked_people, Unavailable) or isinstance(
        reads.pr, Unavailable
    ):
        return SignalResult(0.0, "", "unavailable")
    people = set(reads.blocked_people)
    people.discard(reads.pr.author)
    count = len(people)
    if count == 0:
        return SignalResult(0.0, "", "absent")
    return SignalResult(
        min(1.0, count / config.blocked_people_cap), f"blocks {count} people", "ok"
    )
