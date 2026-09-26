"""Bounded OpenAI-compatible chat-completions client."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

from please_merge_my_pr.config import Config
from please_merge_my_pr.github.auth import AuthError, token
from please_merge_my_pr.github.http import Request, UrllibTransport
from please_merge_my_pr.store import Store

REQUEST_LIMIT = 262_144
RESPONSE_LIMIT = 1_048_576


class ModelError(Exception):
    pass


@dataclass(frozen=True)
class ModelReply:
    content: str | None
    tool_calls: tuple[dict[str, Any], ...]
    input_tokens: int | None
    output_tokens: int | None
    request_bytes: int
    response_bytes: int


class Client:
    def __init__(self, config: Config, store: Store) -> None:
        self.config = config
        self.store = store
        self.egress: list[dict[str, Any]] = []

    def request(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> ModelReply:
        if self.config.model_base_url is None or self.config.model_name is None:
            raise ModelError("model is not configured")
        headers = {"Content-Type": "application/json"}
        if self.config.model_api_key_env is not None:
            key = os.environ.get(self.config.model_api_key_env, "")
            if not key:
                raise ModelError(f"model key not set: {self.config.model_api_key_env}")
            headers["Authorization"] = f"Bearer {key}"
        body: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "max_tokens": 1024,
        }
        if tools is not None:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > REQUEST_LIMIT:
            raise ModelError("model request too large")
        secrets = [os.environ.get(self.config.github_token_env, "")]
        try:
            secrets.append(token(self.config))
        except AuthError:
            pass
        if self.config.model_api_key_env:
            secrets.append(os.environ.get(self.config.model_api_key_env, ""))
        if any(secret and secret.encode() in encoded for secret in secrets):
            raise ModelError("model request blocked: secret detected")
        print("calling model...", file=sys.stderr, flush=True)
        started = time.monotonic()
        response_bytes = 0
        outcome = "ok"
        input_tokens: int | None = None
        output_tokens: int | None = None
        try:
            response = UrllibTransport().send(
                Request(
                    "POST",
                    self.config.model_base_url.rstrip("/") + "/chat/completions",
                    headers,
                    encoded,
                )
            )
            response_bytes = len(response.body)
            if response_bytes > RESPONSE_LIMIT:
                raise ModelError("model response too large")
            if not 200 <= response.status < 300:
                raise ModelError(f"model request failed: HTTP {response.status}")
            try:
                payload = json.loads(response.body)
                choice = payload["choices"][0]
                message = choice["message"]
                if not isinstance(message, dict):
                    raise TypeError
                content = message.get("content")
                calls = message.get("tool_calls") or []
                if content is not None and not isinstance(content, str):
                    raise TypeError
                if not isinstance(calls, list):
                    raise TypeError
                if tools is not None and not content and not calls:
                    raise TypeError
                normalized: list[dict[str, Any]] = []
                for call in calls:
                    if (
                        not isinstance(call, dict)
                        or not isinstance(call.get("id"), str)
                        or call.get("type") != "function"
                        or not isinstance(call.get("function"), dict)
                    ):
                        raise TypeError
                    fn = call["function"]
                    if not isinstance(fn.get("name"), str) or not isinstance(
                        fn.get("arguments"), str
                    ):
                        raise TypeError
                    normalized.append(call)
                usage = payload.get("usage")
                if (
                    isinstance(usage, dict)
                    and isinstance(usage.get("prompt_tokens"), int)
                    and isinstance(usage.get("completion_tokens"), int)
                ):
                    input_tokens = usage["prompt_tokens"]
                    output_tokens = usage["completion_tokens"]
            except (
                IndexError,
                KeyError,
                TypeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                raise ModelError("invalid model response") from None
            return ModelReply(
                content,
                tuple(normalized),
                input_tokens,
                output_tokens,
                len(encoded),
                response_bytes,
            )
        except KeyboardInterrupt:
            outcome = "cancelled"
            raise
        except ModelError:
            outcome = "error"
            raise
        except TimeoutError:
            outcome = "timeout"
            raise ModelError("model request timed out") from None
        except OSError:
            outcome = "network_error"
            raise ModelError("model endpoint unavailable") from None
        finally:
            latency = (time.monotonic() - started) * 1000.0
            self.store.record_call(
                len(encoded),
                response_bytes,
                latency,
                outcome,
                self.config.model_name,
                input_tokens,
                output_tokens,
            )
            self.egress.append(
                {
                    "model": self.config.model_name,
                    "request_bytes": len(encoded),
                    "response_bytes": response_bytes,
                    "outcome": outcome,
                }
            )
