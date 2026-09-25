"""Small injectable HTTP transport."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as UrlRequest


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def send(self, request: Request) -> Response:
        """Return a Response for every HTTP status, 4xx and 5xx included.

        Raise TimeoutError when the request times out, and another OSError
        (for example ConnectionError) for any other network failure.
        """
        ...


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


class UrllibTransport:
    def send(self, request: Request) -> Response:
        raw = UrlRequest(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with build_opener(_NoRedirectHandler()).open(raw, timeout=30) as response:
                return Response(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            return Response(
                status=exc.code,
                headers=dict(exc.headers.items()),
                body=exc.read(),
            )
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("GitHub request timed out") from None
            raise ConnectionError("GitHub request failed") from None
