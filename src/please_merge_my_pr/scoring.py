"""Pure signal scoring and deterministic ranking."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from math import floor, isfinite

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import Event, Reads
from please_merge_my_pr.signals import SignalStatus, registry


@dataclass(frozen=True)
class Row:
    name: str
    value: float
    weight: float
    points: float
    off: float
    fragment: str
    status: SignalStatus


@dataclass(frozen=True)
class Scored:
    score: int
    exact: float
    reason: str
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Entry:
    repo: str
    number: int
    requested_at: datetime
    scored: Scored


@dataclass(frozen=True)
class RankGroup:
    rank: int
    score: int
    entries: tuple[Entry, ...]


def score(
    event: Event,
    reads: Reads,
    weights: Mapping[str, float],
    config: Config,
    now: datetime,
) -> Scored:
    extractors = registry()
    expected = tuple(extractors)
    for name in weights:
        if name not in extractors:
            raise ValueError(f"unknown weight: {name}")
    for name in expected:
        if name not in weights:
            raise ValueError(f"missing weight: {name}")
        value = weights[name]
        if not isfinite(value) or value < 0:
            raise ValueError(f"invalid weight: {name}")
    total = sum(weights.values())
    if total == 0:
        raise ValueError("weights must not all be zero")
    for name, cap in (
        ("age_cap_days", config.age_cap_days),
        ("diff_cap_lines", config.diff_cap_lines),
    ):
        if not isfinite(cap) or cap <= 0:
            raise ValueError(f"invalid {name}")

    result_rows = []
    for name, extractor in extractors.items():
        result = extractor(event, reads, config, now)
        weight = weights[name]
        points = 100.0 * weight * result.value / total
        off = 100.0 * weight * (1.0 - result.value) / total
        result_rows.append(
            Row(
                name=name,
                value=result.value,
                weight=weight,
                points=points,
                off=off,
                fragment=result.fragment,
                status=result.status,
            )
        )
    exact = sum(row.points for row in result_rows)
    fragments = [
        row.fragment
        for row in sorted(
            result_rows,
            key=lambda row: (-row.points, expected.index(row.name)),
        )
        if row.fragment
    ][:3]
    reason = " · ".join(fragments) if fragments else "nothing notable"
    return Scored(
        score=floor(exact + 0.5), exact=exact, reason=reason, rows=tuple(result_rows)
    )


def rank(scored: Iterable[Entry]) -> list[RankGroup]:
    ordered = sorted(
        scored,
        key=lambda entry: (
            -entry.scored.score,
            entry.requested_at,
            entry.repo,
            entry.number,
        ),
    )
    groups: list[RankGroup] = []
    position = 1
    while position <= len(ordered):
        score_value = ordered[position - 1].scored.score
        end = position
        while end < len(ordered) and ordered[end].scored.score == score_value:
            end += 1
        groups.append(
            RankGroup(
                rank=position,
                score=score_value,
                entries=tuple(ordered[position - 1 : end]),
            )
        )
        position = end + 1
    return groups
