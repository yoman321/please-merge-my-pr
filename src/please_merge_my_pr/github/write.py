"""Exact GitHub write execution."""

from __future__ import annotations

from dataclasses import dataclass

from please_merge_my_pr.github.http import Request, Transport


@dataclass(frozen=True)
class WriteResult:
    ok: bool
    status: int


def send(transport: Transport, request: Request) -> WriteResult:
    try:
        response = transport.send(request)
    except (OSError, TimeoutError):
        return WriteResult(False, 0)
    return WriteResult(200 <= response.status < 300, response.status)
