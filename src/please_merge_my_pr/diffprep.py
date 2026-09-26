"""Deterministic bounded unified-diff preparation."""

from __future__ import annotations

from pathlib import PurePosixPath

from please_merge_my_pr.events import FileChange

LIMIT = 65_536


def build(files: tuple[FileChange, ...], lockfiles: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for change in sorted(files, key=lambda item: item.path):
        if any(PurePosixPath(change.path).full_match(pattern) for pattern in lockfiles):
            continue
        if change.patch is None:
            continue
        chunks.append(
            f"diff --git a/{change.path} b/{change.path}\n--- a/{change.path}\n+++ b/{change.path}\n{change.patch}\n"
        )
    raw = "".join(chunks).encode()[:LIMIT]
    while True:
        try:
            return raw.decode()
        except UnicodeDecodeError:
            raw = raw[:-1]
