"""Checks and mergeability signal."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, config, now
    if isinstance(reads.ci, Unavailable) or isinstance(reads.mergeable, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    value = 0.0 if reads.ci == "failing" or not reads.mergeable else 1.0
    return SignalResult(value, "", "ok")
