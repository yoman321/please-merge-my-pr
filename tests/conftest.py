"""Shared builders and guards for the queue-skeleton gates.

Every value here comes from plans/queue-skeleton.md, never from an
implementation.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import traceback
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from please_merge_my_pr.config import Config
from please_merge_my_pr.events import (
    CIState,
    Event,
    FileChange,
    PRDetails,
    Reads,
    ReviewTurn,
    Unavailable,
)
from please_merge_my_pr.github.http import Transport

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"
FIXTURES = TESTS_DIR / "fixtures"

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
API = "https://api.fake-github.test"

# The fixed order of all seven weighted signals, by their canonical
# names from plans/chat.md C22 and C24.
SIGNAL_ORDER = (
    "urgency",
    "blocks",
    "risk",
    "due_soon",
    "age",
    "diff",
    "ci",
)

# Phase 2: the fixed set of Unavailable reasons.
UNAVAILABLE_REASONS = (
    "forbidden",
    "not_found",
    "rate_limited",
    "server_error",
    "network_error",
    "timeout",
    "invalid_response",
    "computing",
    "preview_missing",
    "unmatched",
)

# § Defaults.
DEFAULT_WEIGHTS = {
    "urgency": 30.0,
    "blocks": 25.0,
    "risk": 15.0,
    "due_soon": 10.0,
    "age": 10.0,
    "diff": 5.0,
    "ci": 5.0,
}
DEFAULT_LOCKFILES = (
    "**/uv.lock",
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/poetry.lock",
    "**/Cargo.lock",
    "**/go.sum",
)
DEFAULT_RISK_PATHS = {
    "auth": ("auth/**",),
    "billing": ("billing/**",),
    "migrations": ("migrations/**",),
}

# Phase 1: every retained command, and the plan that owns each stub.
BUILT_COMMANDS = ("list", "why", "show", "watch")
STUBS = {
    "init": "onboarding",
    "config": "onboarding",
    "label": "queue-actions",
    "merge": "queue-actions",
    "comment": "queue-actions",
    "approve": "queue-actions",
    "hide": "queue-actions",
    "snooze": "queue-actions",
    "open": "queue-actions",
    "rules": "queue-actions",
    "egress": "summaries",
}
ALL_COMMANDS = frozenset(BUILT_COMMANDS) | frozenset(STUBS)


def plan_config(**overrides: Any) -> Config:
    """The § Defaults table, spelled out, so gates do not depend on default_config()."""
    values: dict[str, Any] = {
        "weights": dict(DEFAULT_WEIGHTS),
        "age_cap_days": 14.0,
        "diff_cap_lines": 500.0,
        "risk_paths": dict(DEFAULT_RISK_PATHS),
        "lockfiles": DEFAULT_LOCKFILES,
        "repos": (),
        "github_api_url": API,
        "github_token_env": "GITHUB_TOKEN",
    }
    values.update(overrides)
    return Config(**values)


def make_event(
    repo: str = "acme/api",
    number: int = 412,
    base_ref: str = "main",
    head_ref: str = "feature",
) -> Event:
    return Event(repo=repo, number=number, base_ref=base_ref, head_ref=head_ref)


def make_pr(
    *,
    author: str = "alice",
    title: str = "Tidy the session code",
    body: str = "Plain description.",
    labels: tuple[str, ...] = (),
    additions: int = 10,
    deletions: int = 0,
    created_at: datetime = NOW - timedelta(days=30),
    draft: bool = False,
) -> PRDetails:
    return PRDetails(
        author=author,
        title=title,
        body=body,
        labels=tuple(sorted(labels)),
        additions=additions,
        deletions=deletions,
        milestone_due=None,
        created_at=created_at,
        updated_at=created_at,
        draft=draft,
    )


def make_files(*files: tuple[str, int, int]) -> tuple[FileChange, ...]:
    return tuple(
        sorted(
            (FileChange(path=p, additions=a, deletions=d) for p, a, d in files),
            key=lambda f: f.path,
        )
    )


def make_review(
    *,
    requested_at: datetime | None = NOW - timedelta(days=7),
    by_name: bool = True,
    as_code_owner: bool = False,
    requested_by_user: bool = True,
) -> ReviewTurn:
    return ReviewTurn(
        requested_at=requested_at,
        by_name=by_name,
        as_code_owner=as_code_owner,
        requested_by_user=requested_by_user,
    )


def make_reads(
    *,
    pr: PRDetails | Unavailable | None = None,
    files: tuple[FileChange, ...] | Unavailable | None = None,
    review: ReviewTurn | Unavailable | None = None,
    ci: CIState | Unavailable = "passing",
    mergeable: bool | Unavailable = True,
) -> Reads:
    """Defaults: a 10-line change to src/app.py, requested 7 days before NOW, CI green."""
    return Reads(
        pr=pr if pr is not None else make_pr(),
        files=files if files is not None else make_files(("src/app.py", 10, 0)),
        review=review if review is not None else make_review(),
        ci=ci,
        mergeable=mergeable,
    )


# ---- guards --------------------------------------------------------------


class GuardViolation(BaseException):
    """BaseException, so a broad `except Exception` in product code cannot hide it."""


@dataclass
class _GuardState:
    network: bool = False
    writes: bool = False
    any_open: bool = False
    subprocess: bool = False
    violations: list[str] = field(default_factory=list)
    opened: list[str] | None = None


_STATE = _GuardState()

_NETWORK_EVENTS = {
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.sendto",
    "socket.sendmsg",
    "socket.bind",
    "urllib.Request",
    "http.client.connect",
}
_WRITE_EVENTS = {
    "os.mkdir",
    "os.rename",
    "os.remove",
    "os.rmdir",
    "os.truncate",
    "os.symlink",
    "os.link",
    "os.chmod",
    "os.utime",
    "shutil.copyfile",
    "shutil.move",
    "shutil.rmtree",
}
_SUBPROCESS_EVENTS = {
    "subprocess.Popen",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


def _is_write_open(mode: Any, flags: Any) -> bool:
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _violate(message: str) -> None:
    _STATE.violations.append(message)
    raise GuardViolation(message)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if _STATE.opened is not None:
            _STATE.opened.append(
                os.fsdecode(path)
                if isinstance(path, (str, bytes, os.PathLike))
                else str(path)
            )
        if _STATE.any_open:
            _violate(f"file opened: {path!r}")
        if _STATE.writes and _is_write_open(mode, flags):
            _violate(f"file opened for writing: {path!r}")
    elif _STATE.network and event in _NETWORK_EVENTS:
        _violate(f"network: {event}")
    elif event == "sqlite3.connect" and (_STATE.writes or _STATE.any_open):
        if args and str(args[0]) != ":memory:":
            _violate(f"sqlite3.connect {args[0]!r}")
    elif _STATE.writes and event in _WRITE_EVENTS:
        _violate(f"write: {event} {args[:1]!r}")
    elif _STATE.subprocess and event in _SUBPROCESS_EVENTS:
        _violate(f"subprocess: {event}")


sys.addaudithook(_audit)


@contextmanager
def guard(
    *,
    network: bool = False,
    writes: bool = False,
    any_open: bool = False,
    subprocess: bool = False,
) -> Iterator[list[str]]:
    """Make the named kinds of I/O raise GuardViolation. Yields the violation log."""
    saved = (_STATE.network, _STATE.writes, _STATE.any_open, _STATE.subprocess)
    _STATE.violations = []
    _STATE.network, _STATE.writes, _STATE.any_open, _STATE.subprocess = (
        network,
        writes,
        any_open,
        subprocess,
    )
    try:
        yield _STATE.violations
    finally:
        _STATE.network, _STATE.writes, _STATE.any_open, _STATE.subprocess = saved


@contextmanager
def record_opens() -> Iterator[list[str]]:
    opened: list[str] = []
    _STATE.opened = opened
    try:
        yield opened
    finally:
        _STATE.opened = None


# ---- CLI runner ----------------------------------------------------------


@dataclass
class CliResult:
    code: int
    out: str
    err: str
    crash: str  # formatted traceback when main raised something other than SystemExit


def run_cli(argv: Sequence[str], transport: Transport | None = None) -> CliResult:
    from please_merge_my_pr.cli import main

    out, err = io.StringIO(), io.StringIO()
    crash = ""
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = (
                main(list(argv), transport=transport)
                if transport is not None
                else main(list(argv))
            )
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
    return CliResult(
        code=code if isinstance(code, int) else -1,
        out=out.getvalue(),
        err=err.getvalue(),
        crash=crash,
    )


def assert_ran(result: CliResult, code: int = 0) -> None:
    assert not result.crash, result.crash
    assert result.code == code, (
        f"exit {result.code}\nstdout:\n{result.out}\nstderr:\n{result.err}"
    )


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mapping[str, Path]:
    """Empty HOME and XDG dirs, no token, no gh on PATH, plain output, no bytecode writes."""
    dirs = {
        name: tmp_path / name
        for name in ("home", "config", "state", "cache", "data", "bin", "cwd")
    }
    for d in dirs.values():
        d.mkdir()
    monkeypatch.setenv("HOME", str(dirs["home"]))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(dirs["config"]))
    monkeypatch.setenv("XDG_STATE_HOME", str(dirs["state"]))
    monkeypatch.setenv("XDG_CACHE_HOME", str(dirs["cache"]))
    monkeypatch.setenv("XDG_DATA_HOME", str(dirs["data"]))
    monkeypatch.setenv("PATH", str(dirs["bin"]))
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.chdir(dirs["cwd"])
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    return dirs


def write_config(dirs: Mapping[str, Path], text: str) -> Path:
    path = dirs["config"] / "please-merge-my-pr" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def live(
    isolated: Mapping[str, Path], monkeypatch: pytest.MonkeyPatch
) -> Mapping[str, Path]:
    """Isolated, plus a token in the env and a config file pointing at the fake API."""
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    write_config(isolated, f'[github]\napi_url = "{API}"\n')
    return isolated


def all_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def forbid_clock_and_random() -> tuple[
    Callable[[], None], Callable[[], None], list[str]
]:
    """A profiler that logs every clock read and random draw on this thread."""
    import datetime as dt_module
    import random

    seen: list[str] = []
    clock_names = {
        "time",
        "time_ns",
        "monotonic",
        "monotonic_ns",
        "perf_counter",
        "perf_counter_ns",
        "process_time",
        "process_time_ns",
        "localtime",
        "gmtime",
        "ctime",
        "asctime",
        "clock_gettime",
        "clock_gettime_ns",
    }
    python_modules = {
        "random",
        "secrets",
        "uuid",
        "socket",
        "ssl",
        "http.client",
        "urllib.request",
        "sqlite3",
    }

    def profiler(frame: Any, event: str, arg: Any) -> None:
        if event == "c_call":
            name = getattr(arg, "__name__", "")
            owner = getattr(arg, "__self__", None)
            module = getattr(arg, "__module__", None)
            if module == "time" and name in clock_names:
                seen.append(f"time.{name}")
            elif (
                isinstance(owner, type)
                and issubclass(owner, dt_module.date)
                and name in {"now", "utcnow", "today"}
            ):
                seen.append(f"{owner.__name__}.{name}")
            elif isinstance(owner, random.Random) or module == "_random":
                seen.append(f"random.{name}")
            elif name == "urandom":
                seen.append("os.urandom")
        elif event == "call":
            module_name = frame.f_globals.get("__name__", "")
            if module_name in python_modules:
                seen.append(f"{module_name}.{frame.f_code.co_name}")

    return (lambda: sys.setprofile(profiler)), (lambda: sys.setprofile(None)), seen


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to build the wheel"
    out = tmp_path_factory.mktemp("dist")
    proc = subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(out), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    wheels = list(out.glob("please_merge_my_pr-*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]
