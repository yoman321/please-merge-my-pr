"""Exact-label urgency signal."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, now
    if isinstance(reads.pr, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    configured = {
        name.casefold(): value for name, value in (config.urgency_labels or {}).items()
    }
    matches = [
        (label, configured.get(label.casefold(), 0.0)) for label in reads.pr.labels
    ]
    value = max((value for _, value in matches), default=0.0)
    if value == 0.0:
        return SignalResult(0.0, "", "absent")
    label = next(label for label, found in matches if found == value)
    return SignalResult(value, f"{label} priority", "ok")
