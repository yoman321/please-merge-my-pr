"""Plain screen rendering. Domain modules never format terminal output."""

from __future__ import annotations

from collections.abc import Iterable

from please_merge_my_pr.scoring import Row
from please_merge_my_pr.text import wrapped


def list_screen(
    header: str, items: Iterable[tuple[int, str, int]], footer: str | None = None
) -> str:
    lines = [header]
    for number, reason, score in items:
        lines.extend(wrapped(f"#{number} {reason}   [score {score}]"))
    if footer:
        lines.append(footer)
    return "\n".join(lines) + "\n"


def why_screen(
    repo: str, number: int, score: int, exact: float, rows: Iterable[Row]
) -> str:
    lines = [f"{repo}#{number} · score {score}"]
    off = 0.0
    points = 0.0
    for row in rows:
        suffix = "" if row.status == "ok" else f" [{row.status}]"
        fragment = f" · {row.fragment}" if row.fragment else ""
        lines.extend(
            wrapped(
                f"{row.name}: value {row.value:g}, weight {row.weight:g}, points {row.points:g}, off {row.off:g}{fragment}{suffix}"
            )
        )
        points += row.points
        off += row.off
    lines.extend(
        [
            f"Σ points: {points:g}",
            f"100 − Σ off: {100.0 - off:g}",
            f"exact: {exact:g}",
            f"rounded score: {score}",
        ]
    )
    return "\n".join(lines) + "\n"


def show_screen(title: str, reason: str, score: int) -> str:
    return (
        "\n".join(
            [
                *wrapped(title),
                *wrapped(f"{reason}   [score {score}]"),
                "summary: not enabled",
            ]
        )
        + "\n"
    )


def watch_screen(items: Iterable[tuple[str, int, str, int]]) -> str:
    lines: list[str] = []
    for repo, number, reason, score in items:
        lines.extend(wrapped(f"+ {repo}#{number} {reason}   [score {score}]"))
    return "\n".join(lines) + ("\n" if lines else "")
