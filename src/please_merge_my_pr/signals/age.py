"""Current review-request age signal."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event
    if isinstance(reads.review, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    requested = reads.review.requested_at
    if requested is None:
        return SignalResult(0.0, "", "absent")
    hours = max(0.0, (now - requested).total_seconds() / 3600.0)
    value = min(1.0, hours / (config.age_cap_days * 24.0))
    if value == 0.0:
        return SignalResult(0.0, "", "absent")
    fragment = (
        f"waiting {int(hours)}h" if hours < 24 else f"waiting {int(hours // 24)}d"
    )
    return SignalResult(value, fragment, "ok")
