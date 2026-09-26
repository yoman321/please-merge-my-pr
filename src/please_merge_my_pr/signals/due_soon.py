"""Milestone due-date signal."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event
    if isinstance(reads.pr, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    due = reads.pr.milestone_due
    if due is None:
        return SignalResult(0.0, "", "absent")
    days = (due - now).total_seconds() / 86400.0
    value = (
        1.0 if days <= 0 else max(0.0, 1.0 - min(1.0, days / config.due_horizon_days))
    )
    if value == 0.0:
        return SignalResult(0.0, "", "absent")
    return SignalResult(value, "milestone due", "ok")
