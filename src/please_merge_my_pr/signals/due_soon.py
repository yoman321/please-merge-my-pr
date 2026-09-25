"""Placeholder for the later due-date signal."""

from __future__ import annotations

from datetime import datetime

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads
from please_merge_my_pr.signals import SignalResult


def extract(event: Event, reads: Reads, config: Config, now: datetime) -> SignalResult:
    del event, reads, config, now
    return SignalResult(0.0, "", "not_built")
