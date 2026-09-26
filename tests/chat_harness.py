"""Shared harness for the plans/chat.md gates.

Every value here comes from plans/chat.md, never from an implementation.

Contract the gates rely on, so the Build session can read it:

- Chat is `please_merge_my_pr.cli.main([], transport=...)`. GitHub reads and
  writes go through that `transport`. The model client uses real HTTP to
  `model.base_url`, which the gates point at `FakeModel` on 127.0.0.1.
- Chat and every prompt read from `sys.stdin` with `readline()` (or
  `input()`), and check `sys.stdin.isatty()` / `sys.stdout.isatty()`. They
  write to whatever `sys.stdout` / `sys.stderr` are at call time.
- `readline()` returning "" is Ctrl-D / EOF. `readline()` raising
  KeyboardInterrupt is Ctrl-C at a prompt. SIGINT delivered to the main
  thread is Ctrl-C during a request or `/watch`.
- A paste arrives as a bracketed paste: ESC[200~ … ESC[201~, then newline.
- Opening a browser honors `$BROWSER` (stdlib `webbrowser` does).
- Local state lives at `$XDG_STATE_HOME/please-merge-my-pr/state.sqlite3`.
"""

from __future__ import annotations

import io
import json
import re
import signal
import sqlite3
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from conftest import API, GuardViolation
from fake_github_plus import FakeGitHubPlus

TOOLS = (
    "list_queue",
    "why",
    "show",
    "move",
    "open",
    "label",
    "merge",
    "comment",
    "approve",
    "set_weights",
)
TOOL_PARAMS = {
    "list_queue": {"limit"},
    "why": {"pr"},
    "show": {"pr", "summary"},
    "move": {"pr", "before", "after", "position", "reason"},
    "open": {"pr"},
    "label": {"pr", "add", "remove"},
    "merge": {"pr", "method"},
    "comment": {"pr", "body"},
    "approve": {"pr", "body"},
    "set_weights": {"weights"},
}
SLASH_COMMANDS = (
    "list",
    "why",
    "show",
    "watch",
    "hide",
    "unhide",
    "snooze",
    "open",
    "label",
    "merge",
    "comment",
    "approve",
    "rules",
    "reset-view",
    "egress",
    "help",
    "quit",
)
DIRECT_COMMANDS = frozenset(
    {
        "list",
        "why",
        "show",
        "watch",
        "init",
        "config",
        "label",
        "merge",
        "comment",
        "approve",
        "hide",
        "unhide",
        "snooze",
        "open",
        "rules",
        "egress",
    }
)
WEIGHT_KEYS = ("urgency", "blocks", "risk", "due_soon", "age", "diff", "ci")
DEFAULT_WEIGHTS = {
    "urgency": 30.0,
    "blocks": 25.0,
    "risk": 15.0,
    "due_soon": 10.0,
    "age": 10.0,
    "diff": 5.0,
    "ci": 5.0,
}
ALIASES = {"risk": "risk_paths", "diff": "diff_size", "ci": "ci_state"}

PROMPT = "queue> "
MODEL_NAME = "fake-model-7"
KEY_ENV = "MODEL_API_KEY"
KEY_VALUE = "sk-SEEDEDmodelkey-4417"
TOKEN_VALUE = "ghp_SEEDEDgithubtoken-9931"

ERR_UNKNOWN_TOOL = "tool rejected: unknown tool"
ERR_BAD_ARGS = "tool rejected: invalid arguments"
ERR_TOOLS = "turn limit reached: tools"
ERR_REQUESTS = "turn limit reached: requests"
ERR_MOVES = "turn limit reached: moves"
ERR_SECRET = "model request blocked: secret detected"
ERR_USER_BIG = "user input too large"
ERR_REQ_BIG = "model request too large"
ERR_RESP_BIG = "model response too large"
ERR_SUMMARY_LIMIT = "summary limit reached"
ERR_NO_MODEL = "model is not configured"

USER_LIMIT = 16_384
REQUEST_LIMIT = 262_144
RESPONSE_LIMIT = 1_048_576
HISTORY_LIMIT = 196_608
DIFF_LIMIT = 65_536

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b.")


# ---- the fake OpenAI-compatible endpoint ---------------------------------


@dataclass
class Reply:
    """A raw answer. `body` wins over `payload`."""

    status: int = 200
    payload: Any = None
    body: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    before: Callable[[], None] | None = None


@dataclass
class Seen:
    path: str
    headers: dict[str, str]
    body: bytes
    reply_bytes: int = 0
    flushed_markers: int = 0

    @property
    def json(self) -> dict[str, Any]:
        value = json.loads(self.body)
        assert isinstance(value, dict)
        return value

    @property
    def conversational(self) -> bool:
        return "tools" in self.json

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self.json["messages"])

    def tool_results(self) -> dict[str, str]:
        return {
            str(m["tool_call_id"]): str(m["content"])
            for m in self.messages
            if m.get("role") == "tool"
        }

    def last_user(self) -> str:
        users = [m for m in self.messages if m.get("role") == "user"]
        return str(users[-1]["content"])


def completion(
    content: str | None = None,
    calls: Sequence[tuple[str, str, Any]] = (),
    usage: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """An OpenAI chat.completion. calls: (id, name, args dict or raw string)."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": args if isinstance(args, str) else json.dumps(args),
                },
            }
            for call_id, name, args in calls
        ]
    out: dict[str, Any] = {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 1_790_000_000,
        "model": MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if calls else "stop",
            }
        ],
    }
    if usage is not None:
        out["usage"] = {
            "prompt_tokens": usage[0],
            "completion_tokens": usage[1],
            "total_tokens": usage[0] + usage[1],
        }
    return out


def say(text: str, usage: tuple[int, int] | None = None) -> dict[str, Any]:
    return completion(text, (), usage)


def call(
    *calls: tuple[str, str, Any], usage: tuple[int, int] | None = None
) -> dict[str, Any]:
    return completion(None, calls, usage)


def summary_json(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "what_changed": "Refactors the session store.",
        "files": "auth/session.py",
        "risk_notes": "Touches auth.",
        "tests_changed": "None.",
    }
    body.update(overrides)
    for key in [k for k, v in body.items() if v is None]:
        del body[key]
    return say(json.dumps(body))


class FakeModel:
    def __init__(self) -> None:
        self.script: deque[Any] = deque()
        self.seen: list[Seen] = []
        self.lock = threading.Lock()
        self.stderr: Any = None
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: Any) -> None:
                return

            def do_POST(self) -> None:
                fake._handle(self)

            def do_GET(self) -> None:
                fake._handle(self)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def push(self, *items: Any) -> None:
        self.script.extend(items)

    def conversational(self) -> list[Seen]:
        return [s for s in self.seen if s.conversational]

    def summaries(self) -> list[Seen]:
        return [s for s in self.seen if not s.conversational]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        markers = 0
        if self.stderr is not None:
            markers = self.stderr.flushed.count("calling model...")
        seen = Seen(
            handler.path,
            {k.lower(): v for k, v in handler.headers.items()},
            body,
            flushed_markers=markers,
        )
        with self.lock:
            self.seen.append(seen)
            item = self.script.popleft() if self.script else say("default reply")
        reply = item if isinstance(item, Reply) else Reply(payload=item)
        if reply.before is not None:
            reply.before()
        if reply.delay:
            time.sleep(reply.delay)
        data = (
            reply.body if reply.body is not None else json.dumps(reply.payload).encode()
        )
        seen.reply_bytes = len(data)
        try:
            handler.send_response(reply.status)
            headers = {"Content-Type": "application/json", **reply.headers}
            for key, value in headers.items():
                handler.send_header(key, value)
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(data)
        except OSError:
            pass
        handler.close_connection = True


def interrupt_main() -> None:
    """Ctrl-C: SIGINT delivered to the main thread."""
    signal.pthread_kill(threading.main_thread().ident or 0, signal.SIGINT)


# ---- terminal streams ----------------------------------------------------


class Interrupt:
    """readline() raises KeyboardInterrupt (Ctrl-C at a prompt)."""


class Eof:
    """readline() returns "" (Ctrl-D)."""


@dataclass
class Wait:
    seconds: float


INTERRUPT = Interrupt()
EOF = Eof()


def paste(text: str) -> str:
    return f"\x1b[200~{text}\x1b[201~"


class FakeIn(io.TextIOBase):
    def __init__(self, items: Sequence[Any], tty: bool, out: FakeOut) -> None:
        self.items: deque[Any] = deque(items)
        self.tty = tty
        self.out = out
        self.reads = 0

    def isatty(self) -> bool:
        return self.tty

    def readable(self) -> bool:
        return True

    def fileno(self) -> int:
        raise io.UnsupportedOperation("fake stdin")

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def readline(self, size: int | None = -1) -> str:  # type: ignore[override]
        self.reads += 1
        while self.items:
            item = self.items.popleft()
            if isinstance(item, Wait):
                time.sleep(item.seconds)
                continue
            if isinstance(item, Interrupt):
                raise KeyboardInterrupt
            if isinstance(item, Eof):
                return ""
            if callable(item):
                item = item(self.out.getvalue())
            return str(item) + "\n"
        return ""

    def read(self, size: int | None = -1) -> str:
        if size is None or size < 0:
            chunks = []
            while line := self.readline():
                chunks.append(line)
            return "".join(chunks)
        return self.readline()

    def __iter__(self) -> Iterator[str]:  # type: ignore[override]
        while line := self.readline():
            yield line


class FakeOut(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self.tty = tty
        self.flushed = ""

    def isatty(self) -> bool:
        return self.tty

    def fileno(self) -> int:
        raise io.UnsupportedOperation("fake stream")

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return "utf-8"

    def flush(self) -> None:
        super().flush()
        self.flushed = self.getvalue()


@dataclass
class Run:
    code: int
    out: str
    err: str
    crash: str
    stdin: FakeIn

    @property
    def both(self) -> str:
        return self.out + self.err

    def lines(self) -> list[str]:
        """Every output line, with the prompt text taken out of stdout."""
        return self.out.replace(PROMPT, "\n").splitlines() + self.err.splitlines()

    def segments(self) -> list[str]:
        """stdout between prompts: segments()[k] is what the k-th line printed."""
        return self.out.split(PROMPT)[1:]


def run_main(
    argv: Sequence[str],
    transport: Any = None,
    stdin: Sequence[Any] = (),
    *,
    tty_in: bool = True,
    tty_out: bool = True,
    model: FakeModel | None = None,
) -> Run:
    from please_merge_my_pr.cli import main

    out, err = FakeOut(tty_out), FakeOut(tty_out)
    fin = FakeIn(stdin, tty_in, out)
    saved = sys.stdin, sys.stdout, sys.stderr
    if model is not None:
        model.stderr = err
    crash = ""
    sys.stdin, sys.stdout, sys.stderr = fin, out, err
    try:
        try:
            code: Any = main(list(argv), transport=transport)
        except SystemExit as exc:
            code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
        except GuardViolation:
            raise
        except BaseException as exc:  # noqa: BLE001 — record any crash for the assertion
            crash = "".join(traceback.format_exception(exc))
            code = -1
    finally:
        sys.stdin, sys.stdout, sys.stderr = saved
        if model is not None:
            model.stderr = None
    return Run(
        code if isinstance(code, int) else -1,
        out.getvalue(),
        err.getvalue(),
        crash,
        fin,
    )


def chat(
    transport: Any,
    lines: Sequence[Any],
    model: FakeModel | None = None,
    **kwargs: Any,
) -> Run:
    """A chat session: lines, then /quit."""
    return run_main([], transport, [*lines, "/quit"], model=model, **kwargs)


def assert_clean(run: Run, code: int = 0) -> None:
    assert not run.crash, run.crash
    assert "Traceback" not in run.both, run.both
    assert run.code == code, f"exit {run.code}\nstdout:\n{run.out}\nstderr:\n{run.err}"


# ---- config --------------------------------------------------------------


def config_path(dirs: Mapping[str, Path]) -> Path:
    return dirs["config"] / "please-merge-my-pr" / "config.toml"


def state_db(dirs: Mapping[str, Path]) -> Path:
    return dirs["state"] / "please-merge-my-pr" / "state.sqlite3"


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise TypeError(value)


def canonical_config(
    *,
    model_url: str | None = None,
    api_key_env: str | None = KEY_ENV,
    weights: Mapping[str, float] | None = None,
    repos: Sequence[str] = ("acme/api", "acme/web"),
    display_limit: int = 3,
    extra: str = "",
) -> str:
    lines = [
        "[github]",
        f"api_url = {toml_value(API)}",
        'web_url = "https://github.com"',
        'token_env = "GITHUB_TOKEN"',
        f"repos = {toml_value(list(repos))}",
        "",
    ]
    if model_url is not None:
        lines += ["[model]", f"base_url = {toml_value(model_url)}"]
        if api_key_env is not None:
            lines.append(f"api_key_env = {toml_value(api_key_env)}")
        lines += [f"name = {toml_value(MODEL_NAME)}", ""]
    lines.append("[weights]")
    for key, value in (weights or DEFAULT_WEIGHTS).items():
        lines.append(f"{key} = {toml_value(float(value))}")
    lines += [
        "",
        "[scoring]",
        "age_cap_days = 14.0",
        "diff_cap_lines = 500.0",
        "due_horizon_days = 14.0",
        "blocked_people_cap = 3.0",
        "",
        "[urgency_labels]",
        "urgent = 1.0",
        "high = 0.75",
        "medium = 0.5",
        "low = 0.25",
        "",
        "[risk_paths]",
        'auth = ["auth/**"]',
        'billing = ["billing/**"]',
        'migrations = ["migrations/**"]',
        "",
        "[files]",
        'lockfiles = ["**/uv.lock", "**/package-lock.json"]',
        "",
        "[display]",
        f"limit = {display_limit}",
        "",
    ]
    return "\n".join(lines) + extra


def install_config(dirs: Mapping[str, Path], text: str) -> Path:
    path = config_path(dirs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# ---- worlds --------------------------------------------------------------


def queue_world() -> FakeGitHubPlus:
    """Four PRs in acme/api. Default-weight scores 29, 21, 13, 5, all distinct.

    #412 auth, 7d, 380 lines        → 15 + 5 + 3.8 + 5          = 28.8 → 29
    #20  label "low", 7d, 380 lines → 7.5 + 5 + 3.8 + 5         = 21.3 → 21
    #21  6d, 380 lines              → 4.29 + 3.8 + 5            = 13.1 → 13
    #30  1h, 10 lines               → 0.03 + 0.1 + 5            = 5.13 → 5
    """
    now = datetime.now(UTC)
    fake = FakeGitHubPlus(API)
    fake.add_queued(
        "acme/api",
        412,
        now - timedelta(days=7),
        files=[("auth/session.py", 300, 80)],
        title="Rotate session keys",
    )
    fake.add_queued(
        "acme/api",
        20,
        now - timedelta(days=7),
        files=[("src/a.py", 300, 80)],
        title="Speed up the parser",
        labels=["low"],
    )
    fake.add_queued(
        "acme/api",
        21,
        now - timedelta(days=6),
        files=[("src/c.py", 300, 80)],
        title="Add retries",
    )
    fake.add_queued(
        "acme/api",
        30,
        now - timedelta(hours=1),
        files=[("src/b.py", 10, 0)],
        title="Fix a typo",
    )
    return fake


def freeze_clock(monkeypatch: Any) -> datetime:
    """Every `datetime.now` in cli and chat returns one instant, so runs agree."""
    fixed = datetime.now(UTC)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
            return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

    for module in ("cli", "chat"):
        monkeypatch.setattr(f"please_merge_my_pr.{module}.datetime", Frozen)
    return fixed


PRIMARY = re.compile(r"^\s*(?:[\w.-]+/[\w.-]+)?#(\d+)\b.*\[score (\d+)\]")


def primary_rows(text: str) -> list[tuple[int, int, str]]:
    """(number, score, line) for every primary PR row."""
    out = []
    for line in strip_ansi(text).splitlines():
        m = PRIMARY.match(line)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), line))
    return out


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


# ---- side channels -------------------------------------------------------


@contextmanager
def browser_log(dirs: Mapping[str, Path], monkeypatch: Any) -> Iterator[Path]:
    """$BROWSER points at a script that appends each URL to a log."""
    log = dirs["home"] / "browser.log"
    script = dirs["bin"] / "record-browser"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{log}"\n')
    script.chmod(0o755)
    monkeypatch.setenv("BROWSER", f"{script} %s")
    yield log


def browser_urls(log: Path, settle: float = 2.0) -> list[str]:
    deadline = time.monotonic() + settle
    last: list[str] = []
    while time.monotonic() < deadline:
        last = log.read_text().splitlines() if log.exists() else []
        time.sleep(0.1)
    return last


_CONNECTS: list[tuple[Any, int]] | None = None
_CONNECT_STDERR: FakeOut | None = None


def _connect_hook(event: str, args: tuple[Any, ...]) -> None:
    if _CONNECTS is None or event != "socket.connect":
        return
    stream = sys.stderr
    flushed = stream.flushed if isinstance(stream, FakeOut) else ""
    _CONNECTS.append(
        (args[1] if len(args) > 1 else None, flushed.count("calling model..."))
    )


sys.addaudithook(_connect_hook)


@contextmanager
def record_connects() -> Iterator[list[tuple[Any, int]]]:
    """Every socket.connect: (address, flushed 'calling model...' count then)."""
    global _CONNECTS
    found: list[tuple[Any, int]] = []
    _CONNECTS = found
    try:
        yield found
    finally:
        _CONNECTS = None


def all_bytes(root: Path) -> list[tuple[Path, bytes]]:
    return [(p, p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()]


def sqlite_rows(db: Path) -> dict[str, tuple[list[str], list[tuple[Any, ...]]]]:
    """table → (column names, rows)."""
    out: dict[str, tuple[list[str], list[tuple[Any, ...]]]] = {}
    connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        names = [
            str(r[0])
            for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        ]
        for name in names:
            cursor = connection.execute(f'SELECT * FROM "{name}"')
            columns = [d[0] for d in cursor.description]
            out[name] = (columns, list(cursor.fetchall()))
    finally:
        connection.close()
    return out


def env_setup(monkeypatch: Any, *, key: bool = True) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN_VALUE)
    if key:
        monkeypatch.setenv(KEY_ENV, KEY_VALUE)
    else:
        monkeypatch.delenv(KEY_ENV, raising=False)
    monkeypatch.delenv("BROWSER", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)


def future(seconds: float) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


def files_snapshot(paths: Sequence[Path]) -> dict[Path, bytes | None]:
    return {p: (p.read_bytes() if p.exists() else None) for p in paths}


def refs(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"#(\d+)\b", strip_ansi(text))]


# ---- fixtures ------------------------------------------------------------


@dataclass
class Env:
    dirs: Mapping[str, Path]
    model: FakeModel
    github: FakeGitHubPlus
    config: Path

    def chat(self, lines: Sequence[Any], **kwargs: Any) -> Run:
        return chat(self.github, lines, self.model, **kwargs)

    def direct(
        self,
        argv: Sequence[str],
        stdin: Sequence[Any] = (),
        *,
        tty_in: bool = False,
        tty_out: bool = False,
    ) -> Run:
        return run_main(
            argv, self.github, stdin, tty_in=tty_in, tty_out=tty_out, model=self.model
        )

    def configure(self, **kwargs: Any) -> Path:
        kwargs.setdefault("model_url", self.model.base_url)
        return install_config(self.dirs, canonical_config(**kwargs))


@pytest.fixture
def model() -> Iterator[FakeModel]:
    fake = FakeModel()
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def env(
    isolated: Mapping[str, Path], monkeypatch: pytest.MonkeyPatch, model: FakeModel
) -> Env:
    """Isolated dirs, seeded secrets, the four-PR world, a canonical config."""
    env_setup(monkeypatch)
    path = install_config(isolated, canonical_config(model_url=model.base_url))
    return Env(isolated, model, queue_world(), path)
