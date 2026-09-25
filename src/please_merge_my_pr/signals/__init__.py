"""Signal result types and the fixed weighted registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from please_merge_my_pr.config import Config
    from please_merge_my_pr.events import Event, Reads

type SignalStatus = Literal["ok", "absent", "unavailable", "not_built"]


@dataclass(frozen=True)
class SignalResult:
    value: float
    fragment: str
    status: SignalStatus


type Extract = Callable[["Event", "Reads", "Config", datetime], SignalResult]


def registry() -> dict[str, Extract]:
    """All seven weighted signals, name → extract, in the fixed order."""
    from please_merge_my_pr.signals import (
        age,
        blocks,
        ci_state,
        diff_size,
        due_soon,
        risk_paths,
        urgency,
    )

    return {
        "urgency": urgency.extract,
        "blocks": blocks.extract,
        "risk_paths": risk_paths.extract,
        "due_soon": due_soon.extract,
        "age": age.extract,
        "diff_size": diff_size.extract,
        "ci_state": ci_state.extract,
    }
