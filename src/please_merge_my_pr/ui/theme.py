"""Tiny color theme which is inert for plain output."""

from __future__ import annotations

import os
import sys


def color(text: str, code: str) -> str:
    if os.environ.get("NO_COLOR") is not None or not sys.stdout.isatty():
        return text
    return f"\x1b[{code}m{text}\x1b[0m"
