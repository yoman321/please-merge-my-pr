"""Gates for the chat loop: C1–C3, C13, C14, C19–C21, and chat entry.

Planned gates 1–4, 21, 22, 30, 32–36, 59, 60, 63, 64 of plans/chat.md.
"""

from __future__ import annotations

import builtins
import errno
import io
import os
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    DIRECT_COMMANDS,
    EOF,
    ERR_NO_MODEL,
    INTERRUPT,
    KEY_ENV,
    KEY_VALUE,
    PROMPT,
    TOKEN_VALUE,
    Env,
    Reply,
    Wait,
    assert_clean,
    call,
    canonical_config,
    freeze_clock,
    install_config,
    interrupt_main,
    paste,
    primary_rows,
    record_connects,
    say,
    strip_ansi,
)
from fake_github import Failure

# ---- gate 1: slash commands never reach the model ----------------------

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture


def test_g01_slash_commands_make_no_model_request(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chat_harness import browser_log, browser_urls, future

    lines = [
        "/list",
        "/list 2",
        "/why acme/api#412",
        "/show acme/api#412",
        "/hide acme/api#30",
        "/unhide acme/api#30",
        f"/snooze acme/api#21 {future(3600)}",
        "/label acme/api#412 --add bug --remove low",
        "n",
        "/merge acme/api#412 --method squash",
        "n",
        "/comment acme/api#412 hello there zq",
        "n",
        "/approve acme/api#412",
        "n",
        "/rules add acme/api --add bug",
        "/rules list",
        "/rules rm 1",
        "/reset-view",
        "/egress",
        "/help",
        "/no-such-thing",
        "/open acme/api#412",
    ]
    with browser_log(env.dirs, monkeypatch) as log:
        run = env.chat(lines)
        assert browser_urls(log) == ["https://github.com/acme/api/pull/412"]
    assert_clean(run)
    assert env.model.seen == []
    assert "calling model..." not in run.err
    assert "unknown command: /no-such-thing" in run.both
    assert env.github.writes == []


def test_g01_slash_watch_makes_no_model_request(env: Env) -> None:
    timer = threading.Timer(1.5, interrupt_main)
    timer.start()
    try:
        run = env.chat(["/watch", "/list"])
    finally:
        timer.cancel()
    assert_clean(run)
    assert env.model.seen == []
    assert run.out.count(PROMPT) >= 3, run.out  # back at queue> after Ctrl-C


def test_g01_slash_text_never_enters_a_later_request(env: Env) -> None:
    env.model.push(say("fine"))
    run = env.chat(
        [
            "/why acme/api#412",
            "/comment acme/api#412 hello there zq",
            "n",
            "what now?",
        ]
    )
    assert_clean(run)
    assert len(env.model.seen) == 1
    sent = env.model.seen[0].body.decode()
    for leaked in ("/why", "/comment", "hello there zq", "Σ points", "rounded score"):
        assert leaked not in sent, leaked


# ---- gate 2 --------------------------------------------------------------


def test_g02_slash_show_is_code_only(env: Env) -> None:
    run = env.chat(["/show acme/api#412", "/show acme/api#20"])
    assert_clean(run)
    assert env.model.seen == []
    assert not any(line.lstrip().startswith("AI:") for line in run.out.splitlines())


# ---- gate 3 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("slash", "argv"),
    [
        ("/list", ["list"]),
        ("/list 2", ["list", "--limit", "2"]),
        ("/list 50", ["list", "--limit", "50"]),
        ("/why acme/api#412", ["why", "acme/api#412"]),
        ("/why acme/api#30", ["why", "acme/api#30"]),
        ("/show acme/api#412", ["show", "acme/api#412"]),
    ],
)
def test_g03_direct_and_slash_reads_are_byte_equal(
    env: Env, monkeypatch: pytest.MonkeyPatch, slash: str, argv: list[str]
) -> None:
    freeze_clock(monkeypatch)
    direct = env.direct(argv, tty_out=True)
    assert_clean(direct)
    run = env.chat([slash])
    assert_clean(run)
    assert run.segments()[0] == direct.out


# ---- gate 4 --------------------------------------------------------------


def test_g04_direct_reads_make_no_model_request(env: Env) -> None:
    env.github.queue_notifications([env.github.notification("acme/api", 412)])
    with record_connects() as connects:
        runs = [
            env.direct(["list"]),
            env.direct(["list", "--all", "--json"]),
            env.direct(["why", "acme/api#412"]),
            env.direct(["why", "acme/api#412", "--json"]),
            env.direct(["show", "acme/api#412"]),
            env.direct(["watch"]),
        ]
    for run in runs:
        assert_clean(run)
        assert "calling model..." not in run.err
    assert env.model.seen == []
    assert connects == []


# ---- gate 21: model words are marked ----------------------------------


def test_g21_model_lines_start_with_ai_and_code_lines_do_not(env: Env) -> None:
    env.model.push(say("zebra quartz one\nzebra quartz two"))
    run = env.chat(["/list 50", "/why acme/api#412", "how is it going?"])
    assert_clean(run)
    segments = run.segments()
    model_lines = [line for line in segments[2].splitlines() if "quartz" in line]
    assert len(model_lines) >= 2, segments[2]
    for line in model_lines:
        assert line.lstrip().startswith("AI:"), line
    for segment in segments[:2]:
        for line in segment.splitlines():
            assert "AI:" not in line, line
    assert primary_rows(segments[0])


def test_g21_action_preview_is_not_labeled_as_model(env: Env) -> None:
    env.model.push(
        call(("c1", "merge", {"pr": "acme/api#412", "method": "squash"})),
        say("zebra quartz done"),
    )
    run = env.chat(["merge it", "n"])
    assert_clean(run)
    assert "[y/N]" in run.both
    preview = [line for line in run.lines() if "squash" in line]
    assert preview, run.both
    for line in preview:
        assert not line.lstrip().startswith("AI:"), line
    assert env.github.writes == []


# ---- gate 22: the request marker ---------------------------------------


def test_g22_marker_is_flushed_before_every_socket_open(env: Env) -> None:
    env.model.push(
        call(("c1", "list_queue", {"limit": 3})),
        call(("c2", "why", {"pr": "acme/api#412"})),
        say("done"),
    )
    with record_connects() as connects:
        run = env.chat(["rank my queue"])
    assert_clean(run)
    assert len(env.model.seen) == 3
    to_model = [
        flushed
        for address, flushed in connects
        if address and address[1] == env.model.port
    ]
    assert len(to_model) >= 1
    for index, flushed in enumerate(to_model):
        assert flushed >= index + 1, (index, flushed)
    for index, seen in enumerate(env.model.seen):
        assert seen.flushed_markers >= index + 1, (index, seen.flushed_markers)
    assert run.err.count("calling model...") == 3


# ---- gate 30: no background requests ------------------------------------


def test_g30_no_idle_or_post_turn_request(env: Env) -> None:
    env.model.push(say("one answer"))
    run = env.chat([Wait(1.5), "hello", Wait(2.0), "/list", Wait(1.0)])
    assert_clean(run)
    assert len(env.model.seen) == 1
    time.sleep(1.5)
    assert len(env.model.seen) == 1


def test_g30_no_request_without_a_user_turn(env: Env) -> None:
    run = env.chat([Wait(2.0)])
    assert_clean(run)
    time.sleep(1.0)
    assert env.model.seen == []


# ---- gates 32 and 33: terminal output ----------------------------------


LONG_TITLE = " ".join(["Refactor"] * 25)
LONG_AI = " ".join(["quartz"] * 120)
LONG_REASON = " ".join(["reason"] * 28)


def wide(env: Env) -> Env:
    env.github.prs[("acme/api", 412)].title = LONG_TITLE
    return env


def visible_width(line: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in strip_ansi(line)
    )


def all_lines_fit(text: str) -> None:
    for segment in text.split(PROMPT):
        for line in segment.splitlines():
            assert visible_width(line) <= 80, (visible_width(line), line)


def session(env: Env, *, tty_out: bool) -> tuple[list[str], str]:
    env.model.push(
        call(
            (
                "m1",
                "move",
                {"pr": "acme/api#30", "position": "top", "reason": LONG_REASON},
            )
        ),
        say(LONG_AI),
    )
    direct = [
        env.direct(argv, tty_out=tty_out).out
        for argv in (
            ["list", "--all"],
            ["why", "acme/api#412"],
            ["show", "acme/api#412"],
        )
    ]
    run = env.chat(
        [
            "/list 50",
            "/show acme/api#412",
            "/why acme/api#412",
            "/help",
            "move it",
            "/list 50",
        ],
        tty_out=tty_out,
    )
    assert_clean(run)
    return direct, run.out


@pytest.mark.parametrize("mode", ["tty", "no_color"])
def test_g32_output_fits_80_columns(
    env: Env, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    wide(env)
    if mode == "tty":
        monkeypatch.delenv("NO_COLOR", raising=False)
    direct, chat_out = session(env, tty_out=True)
    for text in [*direct, chat_out]:
        all_lines_fit(text)
    ai_lines = [line for line in chat_out.splitlines() if "quartz" in line]
    assert len(ai_lines) >= 9  # 120 words cannot fit in fewer 80-column lines
    for line in ai_lines:
        assert strip_ansi(line).lstrip().startswith("AI:"), line


def test_g33_meaning_survives_without_ansi(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    wide(env)
    plain_direct, plain_chat = session(env, tty_out=True)
    for text in [*plain_direct, plain_chat]:
        assert "\x1b" not in text
    env.model.seen.clear()
    monkeypatch.delenv("NO_COLOR", raising=False)
    color_direct, color_chat = session(env, tty_out=True)
    assert [strip_ansi(t) for t in color_direct] == plain_direct
    assert strip_ansi(color_chat) == plain_chat


@pytest.mark.parametrize("value", ["1", ""])
def test_g33_no_color_turns_ansi_off(
    env: Env, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("NO_COLOR", value)
    direct, chat_out = session(env, tty_out=True)
    for text in [*direct, chat_out]:
        assert "\x1b" not in text


# ---- gate 34: terminal input -------------------------------------------


def test_g34_ctrl_c_at_prompt_returns_to_prompt(env: Env) -> None:
    run = env.chat([INTERRUPT, "/list"])
    assert_clean(run)
    assert run.out.count(PROMPT) >= 3
    assert primary_rows(run.out)


def test_g34_ctrl_c_during_request_returns_to_prompt(env: Env) -> None:
    env.model.push(Reply(payload=say("too late"), before=interrupt_main, delay=3.0))
    env.model.push(say("second answer"))
    run = env.chat(["slow question", "/list", "again"])
    assert_clean(run)
    assert "too late" not in run.out
    assert primary_rows(run.out)
    assert "second answer" in run.out


def test_g34_ctrl_d_on_empty_prompt_exits_cleanly(env: Env) -> None:
    from chat_harness import run_main

    run = run_main([], env.github, [EOF], model=env.model)
    assert_clean(run)
    assert run.stdin.reads == 1
    assert env.model.seen == []


def test_g34_paste_is_one_turn(env: Env) -> None:
    env.model.push(say("got it"))
    run = env.chat([paste("first pasted line\nsecond pasted line\nthird pasted line")])
    assert_clean(run)
    assert len(env.model.seen) == 1
    content = env.model.seen[0].last_user()
    for part in ("first pasted line", "second pasted line", "third pasted line"):
        assert part in content
    assert "\x1b" not in content


def test_g34_paste_read_line_by_line_is_one_turn(env: Env) -> None:
    # A real TTY returns one line per readline(), even inside a bracketed paste.
    env.model.push(say("got it"), say("extra turn"), say("extra turn"))
    run = env.chat(
        [
            "\x1b[200~first pasted line",
            "second pasted line",
            "third pasted line\x1b[201~",
        ]
    )
    assert_clean(run)
    assert len(env.model.seen) == 1, [s.last_user() for s in env.model.seen]
    content = env.model.seen[0].last_user()
    for part in ("first pasted line", "second pasted line", "third pasted line"):
        assert part in content
    assert "\x1b" not in content
    assert "[200~" not in content
    assert "[201~" not in content


def control_chars(text: str) -> list[str]:
    return [c for c in text if unicodedata.category(c) == "Cc" and c not in "\n"]


def test_g34_escapes_and_controls_are_removed(env: Env) -> None:
    env.github.prs[
        ("acme/api", 412)
    ].title = "Evil \x1b[2J\x1b]0;pwn\x07 title\x08\x07 end"
    env.model.push(
        call(
            (
                "c1",
                "comment",
                {"pr": "acme/api#412", "body": "hi \x1b[31mred\x1b[0m \x07there"},
            )
        ),
        say("model \x1b[1mbold\x1b[0m text \x07 done"),
    )
    run = env.chat(["/show acme/api#412", "/list 50", "comment please", "n"])
    assert_clean(run)
    assert control_chars(run.out) == []
    assert control_chars(run.err) == []
    assert "title" in run.out
    assert env.github.writes == []


# ---- gates 35 and 36: model failure ------------------------------------


FAILURES = {
    "invalid_json": Reply(body=b"{not json"),
    "http_500": Reply(status=500, payload={"error": {"message": "boom"}}),
    "http_401": Reply(
        status=401, payload={"error": {"message": f"bad key {KEY_VALUE}"}}
    ),
    "http_429": Reply(status=429, payload={"error": {"message": "slow down"}}),
    "no_choices": Reply(payload={"id": "x", "choices": []}),
    "empty_message": Reply(payload=say(None)),  # type: ignore[arg-type]
    "bad_tool_call": Reply(
        payload={
            "id": "x",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "c1"}],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    ),
    "args_not_object": Reply(payload=call(("c1", "list_queue", "[3]"))),
}


def assert_still_usable(env: Env, run_out: str, direct_list: str) -> None:
    segments = run_out.split(PROMPT)[1:]
    assert direct_list in segments, segments
    assert "recovered fine" in run_out


@pytest.mark.parametrize("kind", sorted(FAILURES))
def test_g35_model_failure_leaves_chat_usable(env: Env, kind: str) -> None:
    direct = env.direct(["list"], tty_out=True)
    env.model.push(FAILURES[kind])
    # args_not_object: the rejected call returns to the model as a tool result.
    env.model.push(say("recovered fine"), say("recovered fine"))
    run = env.chat(["first question", "/list", "second question"])
    assert_clean(run)
    assert_still_usable(env, run.out, direct.out)
    assert KEY_VALUE not in run.both
    assert TOKEN_VALUE not in run.both


def test_g35_unavailable_endpoint_leaves_chat_usable(env: Env) -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    env.configure(model_url=f"http://127.0.0.1:{closed_port}/v1")
    direct = env.direct(["list"], tty_out=True)
    run = env.chat(["first question", "/list", "/why acme/api#412"])
    assert_clean(run)
    assert direct.out in run.out.split(PROMPT)[1:]


def test_g35_timeout_leaves_chat_usable(env: Env) -> None:
    direct = env.direct(["list"], tty_out=True)
    env.model.push(Reply(payload=say("far too late"), delay=33.0))
    started = time.monotonic()
    run = env.chat(["slow question", "/list"])
    elapsed = time.monotonic() - started
    assert_clean(run)
    assert "far too late" not in run.out
    assert direct.out in run.out.split(PROMPT)[1:]
    assert 29.0 <= elapsed < 33.0, elapsed


GITHUB_OUTAGES = {
    "connection_error": Failure(raises=ConnectionError("fake network down")),
    "timeout": Failure(raises=TimeoutError("fake timeout")),
    "http_500": Failure(status=500),
    "http_401": Failure(status=401, body=b'{"message": "Bad credentials"}'),
}
GITHUB_TOOL_CALLS = {
    "list_queue": ("list_queue", {"limit": 3}),
    "why": ("why", {"pr": "acme/api#412"}),
    "show": ("show", {"pr": "acme/api#412", "summary": False}),
}


@pytest.mark.parametrize("tool", sorted(GITHUB_TOOL_CALLS))
@pytest.mark.parametrize("outage", sorted(GITHUB_OUTAGES))
def test_g35_github_failure_during_tool_call_leaves_chat_usable(
    env: Env, outage: str, tool: str
) -> None:
    direct = env.direct(["list"], tty_out=True)
    name, args = GITHUB_TOOL_CALLS[tool]
    env.model.push(call(("c1", name, args)), say("recovered fine"))
    sent: list[int] = []

    def github_down(_out: str) -> str:
        sent.append(len(env.github.requests))
        env.github.fail_everything = GITHUB_OUTAGES[outage]
        return "what should I review?"

    def github_up(_out: str) -> str:
        sent.append(len(env.github.requests))
        env.github.fail_everything = None
        return "/list"

    run = env.chat([github_down, github_up])
    assert_clean(run)
    assert len(sent) == 2 and sent[1] > sent[0], "the tool never reached GitHub"
    assert direct.out in run.out.split(PROMPT)[1:]
    assert KEY_VALUE not in run.both
    assert TOKEN_VALUE not in run.both


@pytest.mark.parametrize("value", [None, ""])
def test_g36_missing_key_prints_error_and_opens_no_socket(
    env: Env, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(KEY_ENV, raising=False)
    else:
        monkeypatch.setenv(KEY_ENV, value)
    direct = env.direct(["list"], tty_out=True)
    with record_connects() as connects:
        run = env.chat(["hello", "/list"])
    assert_clean(run)
    assert f"model key not set: {KEY_ENV}" in run.lines()
    assert env.model.seen == []
    assert connects == []
    assert direct.out in run.out.split(PROMPT)[1:]


def test_g36_no_model_section_sends_nothing(env: Env) -> None:
    install_config(env.dirs, canonical_config(model_url=None))
    with record_connects() as connects:
        run = env.chat(["hello", "/list"])
    assert_clean(run)
    assert ERR_NO_MODEL in run.lines()
    assert env.model.seen == []
    assert connects == []


# ---- gates 59 and 60: chat entry ---------------------------------------


def test_g59_no_subcommand_with_ttys_starts_chat(env: Env) -> None:
    run = env.chat(["/help"])
    assert_clean(run)
    assert run.out.startswith(PROMPT) or PROMPT in run.out
    assert run.stdin.reads >= 2


@pytest.mark.parametrize(
    ("tty_in", "tty_out"),
    [(False, False), (False, True), (True, False)],
    ids=["piped_both", "piped_stdin", "piped_stdout"],
)
def test_g60_no_subcommand_without_ttys_prints_help_and_exits_2(
    env: Env, tty_in: bool, tty_out: bool
) -> None:
    with record_connects() as connects:
        run = env.direct([], ["/help", "hello"], tty_in=tty_in, tty_out=tty_out)
    assert_clean(run, code=2)
    assert "usage: please-merge-my-pr" in run.both, run.both
    missing = {name for name in DIRECT_COMMANDS if name not in run.both}
    assert missing == set(), f"help lacks {sorted(missing)}:\n{run.both}"
    assert PROMPT not in run.both
    assert run.stdin.reads == 0
    assert env.model.seen == []
    assert connects == []


# ---- gate 63: the bracketed-paste switch goes to /dev/tty ---------------

PASTE_ON = "\x1b[?2004h"
PASTE_OFF = "\x1b[?2004l"
DEV_TTY = "/dev/tty"


def fake_dev_tty(monkeypatch: pytest.MonkeyPatch, target: Path | None) -> None:
    """Send every open of /dev/tty to `target`, or fail it when target is None."""
    real_open, real_os_open = builtins.open, os.open

    def is_tty(path: Any) -> bool:
        try:
            return os.fsdecode(path) == DEV_TTY
        except TypeError:
            return False

    def refuse() -> None:
        raise OSError(errno.ENXIO, "Device not configured", DEV_TTY)

    def fake_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if not is_tty(file):
            return real_open(file, mode, *args, **kwargs)
        if target is None:
            refuse()
        append = ("ab" if "b" in mode else "a") + ("+" if "+" in mode else "")
        return real_open(target, append, *args, **kwargs)

    def fake_os_open(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if not is_tty(path):
            return real_os_open(path, flags, mode, **kwargs)
        if target is None:
            refuse()
        return real_os_open(target, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)

    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(io, "open", fake_open)
    monkeypatch.setattr(os, "open", fake_os_open)


@pytest.mark.parametrize("exit_by", ["quit", "ctrl_d", "error"])
def test_g63_paste_switch_is_written_to_dev_tty(
    env: Env, monkeypatch: pytest.MonkeyPatch, exit_by: str
) -> None:
    from chat_harness import run_main

    log = env.dirs["home"] / "dev-tty.log"
    fake_dev_tty(monkeypatch, log)
    at_first_read: list[str] = []

    def first(_out: str) -> str:
        at_first_read.append(log.read_text() if log.exists() else "")
        return "/list"

    def terminal_gone(_out: str) -> str:
        raise OSError(errno.EIO, "Input/output error")

    last = {"quit": "/quit", "ctrl_d": EOF, "error": terminal_gone}[exit_by]
    run = run_main([], env.github, [first, last], model=env.model)
    if exit_by != "error":
        assert_clean(run)
    assert primary_rows(run.out)
    assert at_first_read == [PASTE_ON]  # on at entry, before the first read
    written = log.read_text()
    assert written.startswith(PASTE_ON)
    assert written.endswith(PASTE_OFF)  # off on the way out
    assert "\x1b[?2004" not in run.out
    assert "\x1b[?2004" not in run.err


def test_g63_chat_runs_and_joins_pastes_without_dev_tty(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_dev_tty(monkeypatch, None)
    env.model.push(say("got it"), say("extra turn"), say("extra turn"))
    run = env.chat(
        [
            "\x1b[200~first pasted line",
            "second pasted line",
            "third pasted line\x1b[201~",
            "/list",
        ]
    )
    assert_clean(run)
    assert len(env.model.seen) == 1, [s.last_user() for s in env.model.seen]
    content = env.model.seen[0].last_user()
    for part in ("first pasted line", "second pasted line", "third pasted line"):
        assert part in content
    assert "got it" in run.out
    assert primary_rows(run.out)
    assert "\x1b[?2004" not in run.out
    assert "\x1b[?2004" not in run.err


# ---- gate 64: Ctrl-C during a tool dispatch keeps calls paired -----------


class InterruptOnce:
    """GitHub transport: once armed, its next request raises KeyboardInterrupt."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.armed = False
        self.fired = False

    def send(self, request: Any) -> Any:
        if self.armed:
            self.armed = False
            self.fired = True
            raise KeyboardInterrupt
        return self.inner.send(request)


def assert_calls_paired(messages: list[dict[str, Any]]) -> None:
    """Each tool-call ID has exactly one `tool` result, right after its call."""
    called: set[str] = set()
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        ids = [str(c["id"]) for c in message.get("tool_calls") or []]
        if not ids:
            continue
        called.update(ids)
        following = []
        for later in messages[index + 1 :]:
            if later.get("role") != "tool":
                break
            following.append(str(later["tool_call_id"]))
        assert sorted(following) == sorted(ids), (ids, following)
    results = [str(m["tool_call_id"]) for m in messages if m.get("role") == "tool"]
    assert len(results) == len(set(results)), results
    assert set(results) <= called, (results, called)


def test_g64_ctrl_c_during_tool_dispatch_keeps_calls_paired(env: Env) -> None:
    from chat_harness import chat

    transport = InterruptOnce(env.github)
    env.model.push(
        call(
            ("k1", "why", {"pr": "not a reference"}),  # rejected, never dispatched
            ("k2", "why", {"pr": "acme/api#412"}),  # Ctrl-C lands in this dispatch
            ("k3", "list_queue", {"limit": 3}),  # never reached
        ),
        say("second answer"),
    )

    def arm(_out: str) -> str:
        transport.armed = True
        return "explain 412"

    run = chat(transport, [arm, "and now?", "/list"], env.model)
    assert_clean(run)
    assert transport.fired, "the interrupt never reached a tool dispatch"
    assert len(env.model.seen) == 2
    later = env.model.seen[1]
    assert later.last_user() == "and now?"
    assert_calls_paired(later.messages)
    assert "second answer" in run.out
    assert primary_rows(run.out)
