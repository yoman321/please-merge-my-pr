"""Optional summary slot. Model-backed summaries are a later feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from please_merge_my_pr.events import Event


@dataclass(frozen=True)
class Summary:
    text: str


class Summarizer(Protocol):
    def summarize(self, event: Event, diff: str) -> Summary | None: ...


class NullSummarizer:
    def summarize(self, event: Event, diff: str) -> None:
        del event, diff
