"""Process-local queue ordering overlay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Move:
    pr: str
    reason: str
    position: str | None = None
    before: str | None = None
    after: str | None = None


class Overlay:
    def __init__(self) -> None:
        self.moves: list[Move] = []
        self.reasons: dict[str, str] = {}

    def move(self, args: dict[str, Any]) -> None:
        move = Move(
            str(args["pr"]),
            str(args["reason"]),
            str(args["position"]) if "position" in args else None,
            str(args["before"]) if "before" in args else None,
            str(args["after"]) if "after" in args else None,
        )
        self.moves.append(move)
        self.reasons[move.pr] = move.reason

    def apply(self, items: list[Any]) -> list[Any]:
        ordered = list(items)
        for move in self.moves:
            by_ref = {f"{item.repo}#{item.number}": item for item in ordered}
            item = by_ref.get(move.pr)
            if item is None:
                continue
            ordered.remove(item)
            if move.position == "top":
                ordered.insert(0, item)
            elif move.position == "bottom":
                ordered.append(item)
            elif move.before in by_ref and by_ref[move.before] in ordered:
                ordered.insert(ordered.index(by_ref[move.before]), item)
            elif move.after in by_ref and by_ref[move.after] in ordered:
                ordered.insert(ordered.index(by_ref[move.after]) + 1, item)
            else:
                ordered.append(item)
        return ordered

    def clear(self) -> None:
        self.moves.clear()
        self.reasons.clear()

    def reason(self, repo: str, number: int) -> str | None:
        return self.reasons.get(f"{repo}#{number}")
