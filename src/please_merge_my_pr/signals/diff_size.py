"""Non-lockfile diff-size signal."""

from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads, Unavailable
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, now
    if isinstance(reads.pr, Unavailable) or isinstance(reads.files, Unavailable):
        return SignalResult(0.0, "", "unavailable")
    total = max(0, reads.pr.additions + reads.pr.deletions)
    discounted = sum(
        max(0, change.additions + change.deletions)
        for change in reads.files
        if any(PurePosixPath(change.path).full_match(p) for p in config.lockfiles)
    )
    lines = max(0, total - discounted)
    value = min(1.0, lines / config.diff_cap_lines)
    if value == 0.0:
        return SignalResult(0.0, "", "absent")
    return SignalResult(value, f"{lines} lines", "ok")
