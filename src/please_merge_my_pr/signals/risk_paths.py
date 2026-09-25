"""Risk-path signal."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, now
    if isinstance(reads.files, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    for group, patterns in config.risk_paths.items():
        if any(
            PurePosixPath(change.path).full_match(pattern)
            for pattern in patterns
            for change in reads.files
        ):
            return SignalResult(1.0, f"touches {group}", "ok")
    return SignalResult(0.0, "", "absent")
