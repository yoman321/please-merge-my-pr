"""Safe, narrow terminal text."""

from __future__ import annotations

import re
import textwrap
import unicodedata

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b.")


def clean(value: str) -> str:
    value = ANSI.sub("", value)
    return "".join(
        ch for ch in value if ch in "\n\t" or unicodedata.category(ch) != "Cc"
    )


def wrapped(
    value: str, *, prefix: str = "", continuation: str | None = None, width: int = 80
) -> list[str]:
    value = clean(value)
    following = prefix if continuation is None else continuation
    lines: list[str] = []
    for raw in value.splitlines() or [""]:
        parts = textwrap.wrap(
            raw,
            width=max(1, width - len(prefix)),
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        for index, part in enumerate(parts):
            lead = prefix if not lines and index == 0 else following
            lines.append(lead + part)
    return lines


def ai_lines(value: str) -> str:
    return "\n".join(wrapped(value, prefix="AI: ", continuation="AI: ")) + "\n"
