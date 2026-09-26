"""Gates for the model client and turn loop: C9, C16–C18, C27, C28.

Planned gates 15, 16, 25–29, 31, 56–58, 68, 69 of plans/chat.md.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    ERR_REQ_BIG,
    ERR_REQUESTS,
    ERR_RESP_BIG,
    ERR_SECRET,
    ERR_USER_BIG,
    HISTORY_LIMIT,
    KEY_VALUE,
    MODEL_NAME,
    PROMPT,
    REQUEST_LIMIT,
    RESPONSE_LIMIT,
    TOKEN_VALUE,
    USER_LIMIT,
    Env,
    FakeModel,
    Reply,
    all_bytes,
    assert_clean,
    call,
    compact_json,
    primary_rows,
    record_connects,
    say,
    sqlite_rows,
    state_db,
    summary_json,
)

# ---- gate 15: destinations ----------------------------------------------

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture


REJECTED_URLS = [
    "http://localhost:8080/v1",
    "http://LOCALHOST/v1",
    "http://example.com/v1",
    "http://10.0.0.5/v1",
    "http://[::2]/v1",
    "http://[::ffff:127.0.0.1]/v1",
    "http://0x7f000001/v1",
    "http://127.1/v1",
    "http://user:pw@127.0.0.1:9/v1",
    "https://user@api.example.invalid/v1",
    "https://api.example.invalid/v1?x=1",
    "https://api.example.invalid/v1#frag",
    "ftp://127.0.0.1/v1",
    "ws://127.0.0.1/v1",
    "127.0.0.1:9/v1",
    "",
]


@pytest.mark.parametrize("url", REJECTED_URLS)
def test_g15_forbidden_destinations_are_rejected_before_any_request(
    env: Env, url: str
) -> None:
    env.configure(model_url=url)
    with record_connects() as connects:
        direct = env.direct(["list"])
        run = env.chat(["hello"])
    for result in (direct, run):
        assert not result.crash, result.crash
        assert result.code != 0
        assert "model.base_url" in result.both
    assert env.github.requests == []
    assert env.model.seen == []
    assert connects == []


@pytest.mark.parametrize(
    "url",
    [
        "https://api.example.invalid/v1",
        "http://127.0.0.1:9/v1",
        "http://127.5.6.7:9/v1",
        "http://127.255.255.254/v1",
        "http://[::1]:9/v1",
    ],
)
def test_g15_https_and_literal_loopback_are_accepted(env: Env, url: str) -> None:
    env.configure(model_url=url)
    run = env.direct(["list"])
    assert_clean(run)
    assert "model.base_url" not in run.both


def test_g15_bearer_only_when_key_env_is_set(env: Env) -> None:
    env.model.push(say("one"), say("two"))
    assert_clean(env.chat(["hello"]))
    assert env.model.seen[0].headers["authorization"] == f"Bearer {KEY_VALUE}"
    env.configure(api_key_env=None)
    assert_clean(env.chat(["hello again"]))
    assert "authorization" not in env.model.seen[1].headers
    assert env.model.seen[1].path == "/v1/chat/completions"


# ---- gate 16: redirects -------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_g16_redirects_are_not_followed(env: Env, status: int) -> None:
    elsewhere = FakeModel()
    try:
        target = f"{elsewhere.base_url}/chat/completions"
        env.model.push(Reply(status=status, payload={}, headers={"Location": target}))
        env.model.push(say("recovered fine"))
        direct = env.direct(["list"], tty_out=True)
        run = env.chat(["hello", "/list", "again"])
        assert_clean(run)
        assert elsewhere.seen == []
        assert len(env.model.seen) == 2
        assert direct.out in run.out.split(PROMPT)[1:]
        assert "recovered fine" in run.out
    finally:
        elsewhere.close()


# ---- gates 25 and 26: secrets -------------------------------------------


def assert_blocked(env: Env, run: Any, sent: int) -> None:
    assert_clean(run)
    assert ERR_SECRET in run.lines()
    assert len(env.model.seen) == sent
    for seen in env.model.seen:
        assert TOKEN_VALUE.encode() not in seen.body
        assert KEY_VALUE.encode() not in seen.body


@pytest.mark.parametrize("secret", [TOKEN_VALUE, KEY_VALUE])
def test_g25_secret_in_tool_output_blocks_the_request(env: Env, secret: str) -> None:
    env.github.prs[("acme/api", 412)].body = f"debug dump: token={secret} end"
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": False})), say("never")
    )
    run = env.chat(["show me 412", "/list"])
    assert_blocked(env, run, 1)
    assert primary_rows(run.out)


@pytest.mark.parametrize("secret", [TOKEN_VALUE, KEY_VALUE])
def test_g25_secret_typed_by_user_blocks_the_request(env: Env, secret: str) -> None:
    run = env.chat([f"my key is {secret}"])
    assert_blocked(env, run, 0)


def test_g25_secret_in_summary_input_blocks_the_request(env: Env) -> None:
    env.github.more("acme/api", 412).patches["auth/session.py"] = (
        f"@@ -1 +1 @@\n+TOKEN={TOKEN_VALUE}"
    )
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": True})), say("ok")
    )
    run = env.chat(["summarize 412"])
    assert_clean(run)
    assert ERR_SECRET in run.both or any(
        ERR_SECRET.encode() in s.body for s in env.model.seen
    )
    assert env.model.summaries() == []
    for seen in env.model.seen:
        assert TOKEN_VALUE.encode() not in seen.body


def test_g25_secret_between_quotes_is_still_caught(env: Env) -> None:
    env.github.prs[("acme/api", 412)].title = f'quote"{TOKEN_VALUE}"quote'
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": False})), say("never")
    )
    run = env.chat(["show me"])
    assert_blocked(env, run, 1)


def test_g26_errors_and_files_never_hold_secrets(
    env: Env, isolated: Mapping[str, Path]
) -> None:
    env.github.prs[("acme/api", 412)].body = f"token={TOKEN_VALUE}"
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": False})),
        Reply(
            status=401,
            payload={"error": {"message": f"bad key {KEY_VALUE} for {TOKEN_VALUE}"}},
        ),
        Reply(status=500, body=f"<html>{KEY_VALUE}</html>".encode()),
        Reply(status=200, body=f'{{"oops": "{KEY_VALUE}"'.encode()),
    )
    run = env.chat(["show", "again", "third", "fourth", "/egress"])
    assert_clean(run)
    for secret in (TOKEN_VALUE, KEY_VALUE):
        assert secret not in run.both
        for path, data in all_bytes(isolated["home"].parent):
            assert secret.encode() not in data, path


def test_g26_github_auth_failure_hides_token(env: Env) -> None:
    from fake_github import Failure

    env.github.fail_everything = Failure(
        status=401, body=f'{{"message": "{TOKEN_VALUE}"}}'.encode()
    )
    direct, session = env.direct(["list"]), env.chat(["/list"])
    assert session.out.startswith(PROMPT) or PROMPT in session.out  # chat ran
    for run in (direct, session):
        assert not run.crash
        assert TOKEN_VALUE not in run.both


# ---- gate 27: content is not stored -------------------------------------


MARKS = {
    "user": "QZUSERMARK",
    "response": "QZRESPMARK",
    "title": "QZTITLEMARK",
    "body": "QZBODYMARK",
    "comment": "QZCOMMENTMARK",
    "summary": "QZSUMMARYMARK",
    "reason": "QZREASONMARK",
    "diff": "QZDIFFMARK",
}


def test_g27_content_never_reaches_disk(env: Env, isolated: Mapping[str, Path]) -> None:
    pr = env.github.prs[("acme/api", 412)]
    pr.title = f"{MARKS['title']} title"
    pr.body = f"{MARKS['body']} body"
    env.github.more("acme/api", 412).patches["auth/session.py"] = (
        f"@@ -1 +1 @@\n+{MARKS['diff']}"
    )
    weights = {
        "urgency": 1,
        "blocks": 1,
        "risk": 1,
        "due_soon": 1,
        "age": 1,
        "diff": 1,
        "ci": 1,
    }
    env.model.push(
        call(
            ("c1", "show", {"pr": "acme/api#412", "summary": True}),
            (
                "c2",
                "move",
                {
                    "pr": "acme/api#30",
                    "position": "top",
                    "reason": f"{MARKS['reason']} r",
                },
            ),
            ("c3", "comment", {"pr": "acme/api#412", "body": f"{MARKS['comment']} c"}),
            ("c4", "set_weights", {"weights": weights}),
        ),
        summary_json(what_changed=f"{MARKS['summary']} s"),
        say(f"{MARKS['response']} done"),
    )
    assert_clean(env.direct(["rules", "add", "acme/api", "--add", "bug"]))
    assert_clean(env.direct(["hide", "acme/api#21"]))
    run = env.chat([f"{MARKS['user']} please", "y", "y", "/list 50", "/egress"])
    assert_clean(run)
    assert len(env.github.writes) == 1
    assert (env.config.parent / "config.toml.bak").exists()
    assert state_db(env.dirs).exists()
    for path, data in all_bytes(isolated["home"].parent):
        for kind, mark in MARKS.items():
            assert mark.encode() not in data, (kind, path)


# ---- gate 28: limits at exact boundaries ------------------------------


def test_g28_user_line_limit(env: Env) -> None:
    fits = "é" * (USER_LIMIT // 2)
    assert len(fits.encode()) == USER_LIMIT
    env.model.push(say("fits"))
    run = env.chat([fits, fits + "a", "a" * (USER_LIMIT + 1)])
    assert_clean(run)
    assert len(env.model.seen) == 1
    assert run.lines().count(ERR_USER_BIG) == 2


def show_turn(env: Env, body_len: int) -> int:
    """One show() turn with a PR body of body_len ASCII bytes. Returns request 2 size."""
    env.model.seen.clear()
    env.model.script.clear()
    env.github.prs[("acme/api", 412)].body = "a" * body_len
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": False})), say("ok")
    )
    run = env.chat(["show 412"])
    assert_clean(run)
    assert len(env.model.seen) == 2, run.both
    return len(env.model.seen[1].body)


def test_g28_request_limit_is_exact(env: Env) -> None:
    first = show_turn(env, 10_000)
    second = show_turn(env, 20_000)
    assert second - first == 10_000  # the body is sent whole, byte for byte
    at_limit = 10_000 + (REQUEST_LIMIT - first)
    assert show_turn(env, at_limit) == REQUEST_LIMIT

    env.model.seen.clear()
    env.model.script.clear()
    env.github.prs[("acme/api", 412)].body = "a" * (at_limit + 1)
    env.model.push(
        call(("d1", "show", {"pr": "acme/api#412", "summary": False})), say("never")
    )
    run = env.chat(["show 412", "/list"])
    assert_clean(run)
    assert len(env.model.seen) == 1
    assert ERR_REQ_BIG in run.lines()
    assert primary_rows(run.out)


def padded(text: str, size: int) -> bytes:
    raw = json.dumps(say(text)).encode()
    assert len(raw) <= size
    return raw + b" " * (size - len(raw))


def test_g28_response_limit_is_exact(env: Env) -> None:
    env.model.push(
        Reply(body=padded("exactly at the limit", RESPONSE_LIMIT)),
        Reply(body=padded("one byte over", RESPONSE_LIMIT + 1)),
        say("recovered fine"),
    )
    run = env.chat(["first", "second", "third"])
    assert_clean(run)
    assert "exactly at the limit" in run.out
    assert "one byte over" not in run.out
    assert ERR_RESP_BIG in run.lines()
    assert "recovered fine" in run.out
    assert len(env.model.seen) == 3


def test_g28_request_count_limit_is_exact(env: Env) -> None:
    for i in range(1, 12):
        env.model.push(call((f"r{i}", "list_queue", {"limit": 1})))
    run = env.chat(["loop forever", "/list"])
    assert_clean(run)
    assert len(env.model.seen) == 8
    assert ERR_REQUESTS in run.lines()
    assert primary_rows(run.out)


def test_g28_limits_reset_each_turn(env: Env) -> None:
    for i in range(1, 8):
        env.model.push(call((f"a{i}", "list_queue", {"limit": 1})))
    env.model.push(say("first done"))
    for i in range(1, 8):
        env.model.push(call((f"b{i}", "list_queue", {"limit": 1})))
    env.model.push(say("second done"))
    run = env.chat(["one", "two"])
    assert_clean(run)
    assert len(env.model.seen) == 16
    assert ERR_REQUESTS not in run.both
    assert "second done" in run.out


def test_g28_every_request_is_within_the_byte_and_token_caps(env: Env) -> None:
    env.model.push(call(("c1", "list_queue", {"limit": 50})), say("ok"))
    assert_clean(env.chat(["go"]))
    for seen in env.model.seen:
        assert len(seen.body) <= REQUEST_LIMIT
        assert seen.json["max_tokens"] == 1024


# ---- gate 29: history pruning -------------------------------------------


TURN_BYTES = 58_000


def filler(tag: str, size: int) -> str:
    word = f"{tag} "
    return (word * (size // len(word) + 1))[:size].strip()


def test_g29_pruning_keeps_system_current_and_whole_turns(env: Env) -> None:
    env.github.prs[("acme/api", 412)].body = filler("bodyt3", TURN_BYTES // 2)
    for k in range(1, 6):
        if k == 3:
            env.model.push(
                call(("keep_pair_3", "show", {"pr": "acme/api#412", "summary": False})),
                say(filler("anst3", TURN_BYTES // 2)),
            )
        else:
            env.model.push(say(filler(f"anst{k}", TURN_BYTES)))
    env.model.push(say("current answer"))
    run = env.chat([f"turn {k}" for k in range(1, 6)] + ["current turn"])
    assert_clean(run)
    last = env.model.seen[-1]
    messages = last.messages
    assert messages[0]["role"] == "system"
    assert (messages[-1]["role"], messages[-1]["content"]) == ("user", "current turn")
    earlier = messages[1:-1]
    users = [m["content"] for m in earlier if m["role"] == "user"]
    assert users == ["turn 3", "turn 4", "turn 5"]
    assert earlier[0]["role"] == "user"
    calls = [
        c["id"]
        for m in earlier
        if m["role"] == "assistant"
        for c in m.get("tool_calls") or []
    ]
    results = [m["tool_call_id"] for m in earlier if m["role"] == "tool"]
    assert calls == results == ["keep_pair_3"]
    assert len(compact_json(earlier).encode()) <= HISTORY_LIMIT
    text = json.dumps(earlier)
    for k in (3, 4, 5):
        assert f"anst{k}" in text
    for k in (1, 2):
        assert f"anst{k}" not in text


def test_g29_tool_pair_is_dropped_whole(env: Env) -> None:
    env.github.prs[("acme/api", 412)].body = filler("bodyt1", 100_000)
    env.model.push(
        call(("drop_pair_1", "show", {"pr": "acme/api#412", "summary": False})),
        say("short"),
        say(filler("anst2", 120_000)),
        say("current answer"),
    )
    run = env.chat(["turn 1", "turn 2", "current turn"])
    assert_clean(run)
    messages = env.model.seen[-1].messages
    ids = json.dumps(messages)
    assert "drop_pair_1" not in ids
    assert "bodyt1" not in ids
    users = [m["content"] for m in messages if m["role"] == "user"]
    assert users == ["turn 2", "current turn"]


# ---- gate 31: request and turn records ---------------------------------


def rows_with(db: Path, *values: Any) -> list[tuple[str, list[str], tuple[Any, ...]]]:
    out = []
    for table, (columns, rows) in sqlite_rows(db).items():
        for row in rows:
            if all(v in row for v in values):
                out.append((table, columns, row))
    return out


def turn_table(db: Path) -> tuple[list[str], list[tuple[Any, ...]]]:
    found = [
        (c, r) for _, (c, r) in sqlite_rows(db).items() if "token_usage_complete" in c
    ]
    assert len(found) == 1, sorted(sqlite_rows(db))
    return found[0]


# Seeded provider token counts. Each is above 3,000,000, so none can equal a byte
# count: one request is at most 262,144 bytes and one response at most 1,048,576.
USAGE_A = (7_331_001, 4_441_003)
USAGE_B = (1_009_005, 2_003_007)
USAGE_C = (5_170_011, 6_190_013)


def test_g31_records_hold_exact_bytes_and_honest_tokens(env: Env) -> None:
    env.model.push(
        call(("c1", "list_queue", {"limit": 2}), usage=USAGE_A),
        say("first done", usage=USAGE_B),
        call(("c2", "list_queue", {"limit": 2}), usage=USAGE_C),
        say("second done"),
    )
    run = env.chat(["first turn", "second turn"])
    assert_clean(run)
    seen = env.model.seen
    assert len(seen) == 4
    db = state_db(env.dirs)
    tokens = {
        *USAGE_A,
        *USAGE_B,
        *USAGE_C,
        USAGE_A[0] + USAGE_B[0],
        USAGE_A[1] + USAGE_B[1],
    }
    sizes = {len(s.body) for s in seen} | {s.reply_bytes for s in seen}
    assert tokens.isdisjoint(sizes)  # the numbers below can only mean one thing

    for index, usage in enumerate([USAGE_A, USAGE_B, USAGE_C, None]):
        request_bytes, response_bytes = len(seen[index].body), seen[index].reply_bytes
        matches = rows_with(db, request_bytes, response_bytes, MODEL_NAME)
        assert len(matches) == 1, (index, request_bytes, response_bytes)
        _, _, row = matches[0]
        if usage is None:
            assert sum(v is None for v in row) >= 2, row
            assert tokens.isdisjoint(row), row
        else:
            assert usage[0] in row and usage[1] in row, row

    columns, rows = turn_table(db)
    complete = columns.index("token_usage_complete")
    first_bytes = len(seen[0].body) + len(seen[1].body)
    first_reply = seen[0].reply_bytes + seen[1].reply_bytes
    second_bytes = len(seen[2].body) + len(seen[3].body)
    second_reply = seen[2].reply_bytes + seen[3].reply_bytes
    [first] = [r for r in rows if first_bytes in r and first_reply in r]
    [second] = [r for r in rows if second_bytes in r and second_reply in r]
    assert 2 in first and 2 in second  # request count
    assert bool(first[complete]) is True
    assert USAGE_A[0] + USAGE_B[0] in first and USAGE_A[1] + USAGE_B[1] in first
    assert not bool(second[complete])
    assert tokens.isdisjoint(second), second  # no partial or guessed totals
    assert sum(v is None for v in second) >= 2, second


# ---- gate 56: row shapes ------------------------------------------------


ALLOWED_TEXT = [
    re.compile(r"^[\w.-]+/[\w.-]+(#\d+)?$"),
    re.compile(r"^\d{4}-\d\d-\d\d([T ][\d:.]+)?(Z|[+-]\d\d:?\d\d)?$"),
    re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$"),
    re.compile(r"^\[(\"[\w.-]{1,50}\"(, ?)?)*\]$"),
    re.compile(r"^[\w.-]{1,50}(,[\w.-]{1,50})*$"),
]
FORBIDDEN_COLUMNS = re.compile(
    r"prompt|content|body|reason|title|summary|message|text|diff|patch|comment|payload",
    re.IGNORECASE,
)


def test_g56_rows_hold_only_allowed_fields(env: Env) -> None:
    env.model.push(
        call(
            (
                "m1",
                "move",
                {
                    "pr": "acme/api#30",
                    "position": "top",
                    "reason": "because it is small",
                },
            )
        ),
        say("a long model answer with many words in it"),
        Reply(status=500, payload={"error": {"message": "boom"}}),
    )
    assert_clean(
        env.direct(
            ["rules", "add", "acme/api", "--add", "bug", "ui", "--remove", "low"]
        )
    )
    assert_clean(env.direct(["hide", "acme/api#21"]))
    assert_clean(env.direct(["snooze", "acme/api#20", "2099-01-01T00:00:00+00:00"]))
    assert_clean(env.chat(["please move the small one up", "and again"]))
    tables = sqlite_rows(state_db(env.dirs))
    assert tables
    for table, (columns, rows) in tables.items():
        for column in columns:
            assert not FORBIDDEN_COLUMNS.search(column), (table, column)
        for row in rows:
            for value in row:
                if value is None or isinstance(value, (int, float)):
                    continue
                assert isinstance(value, str), (table, value)
                assert any(p.match(value) for p in ALLOWED_TEXT), (table, value)
                assert "because" not in value and "answer" not in value


# ---- gates 57 and 58: egress --------------------------------------------


def test_g57_egress_shows_this_session_only_and_calls_nothing(env: Env) -> None:
    env.model.push(say("session one"))
    assert_clean(env.chat(["x" * 5000]))
    old_bytes = len(env.model.seen[0].body)
    env.model.seen.clear()
    env.model.push(say("session two"))
    run = env.chat(["short question", "/egress"])
    assert_clean(run)
    assert len(env.model.seen) == 1
    new_bytes = len(env.model.seen[0].body)
    egress = run.segments()[1]
    assert str(new_bytes) in egress
    assert MODEL_NAME in egress
    assert str(old_bytes) not in egress
    for secret in (KEY_VALUE, TOKEN_VALUE):
        assert secret not in run.both
    run = env.chat(["/egress"])
    assert_clean(run)
    assert str(new_bytes) not in run.segments()[0]
    assert len(env.model.seen) == 1


def test_g58_direct_egress_is_chat_only(env: Env) -> None:
    first = env.direct(["egress"])
    second = env.direct(["egress"])
    for run in (first, second):
        assert not run.crash, run.crash
        assert run.code == 2
        assert "chat" in run.both.lower()
        assert "not built yet" not in run.both
    assert first.both == second.both
    assert env.model.seen == []
    assert env.github.requests == []


# ---- gate 68: the token GitHub reads use is the token that is scanned ----

GH_CLI_TOKEN = "gho_SEEDEDfromGhCli-5521"


def token_source(env: Env, monkeypatch: pytest.MonkeyPatch, source: str) -> str:
    """Set up where the GitHub token comes from. Return the exact token."""
    if source == "gh":
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        script = env.dirs["bin"] / "gh"
        script.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "auth" ] && [ "$2" = "token" ]; then\n'
            f'  printf "%s\\n" "{GH_CLI_TOKEN}"\n'
            "  exit 0\n"
            "fi\n"
            "exit 1\n"
        )
        script.chmod(0o755)
        return GH_CLI_TOKEN
    monkeypatch.setenv("GITHUB_TOKEN", f"  {TOKEN_VALUE}\n")
    return TOKEN_VALUE


@pytest.mark.parametrize("where", ["typed", "tool_output"])
@pytest.mark.parametrize("source", ["gh", "padded_env"])
def test_g68_token_in_use_blocks_the_request(
    env: Env, monkeypatch: pytest.MonkeyPatch, source: str, where: str
) -> None:
    secret = token_source(env, monkeypatch, source)
    if where == "typed":
        lines, sent = [f"my token is {secret}", "/list"], 0
    else:
        env.github.prs[("acme/api", 412)].body = f"debug dump: token={secret} end"
        env.model.push(
            call(("d1", "show", {"pr": "acme/api#412", "summary": False})),
            say("never"),
        )
        lines, sent = ["show me 412", "/list"], 1
    with record_connects() as connects:
        run = env.chat(lines)
    assert_clean(run)
    assert ERR_SECRET in run.lines()
    assert len(env.model.seen) == sent
    for seen in env.model.seen:
        assert secret.encode() not in seen.body
    to_model = [
        address
        for address, _ in connects
        if isinstance(address, tuple) and address[1] == env.model.port
    ]
    assert len(to_model) == sent
    assert secret not in run.both
    assert primary_rows(run.out)  # GitHub reads still use the same token


# ---- gate 69: the response body is read with a bound ---------------------


def count_body_reads(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Every http.client response, each with `_gate_bytes`: body bytes pulled out."""
    responses: list[Any] = []
    state = threading.local()

    def wrap(name: str) -> None:
        original = getattr(http.client.HTTPResponse, name)

        def counted(self: Any, *args: Any, **kwargs: Any) -> Any:
            depth = getattr(state, "depth", 0)
            state.depth = depth + 1
            try:
                result = original(self, *args, **kwargs)
            finally:
                state.depth = depth
            if depth == 0:
                if isinstance(result, int):
                    got = result
                elif isinstance(result, (bytes, bytearray)):
                    got = len(result)
                elif isinstance(result, list):
                    got = sum(len(line) for line in result)
                else:
                    got = 0
                if not hasattr(self, "_gate_bytes"):
                    self._gate_bytes = 0
                    responses.append(self)
                self._gate_bytes += got
            return result

        monkeypatch.setattr(http.client.HTTPResponse, name, counted)

    for name in ("read", "read1", "readinto", "readinto1", "readline", "readlines"):
        wrap(name)
    return responses


class CloseDelimitedModel:
    """Answers each POST with a 200 JSON body that has no Content-Length."""

    def __init__(self, size: int) -> None:
        self.body = padded("far too big", size)
        self.requests = 0
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = int(self.server.getsockname()[1])
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                self.requests += 1
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                head, _, rest = data.partition(b"\r\n\r\n")
                match = re.search(rb"(?i)content-length:\s*(\d+)", head)
                length = int(match.group(1)) if match else 0
                while len(rest) < length:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    rest += chunk
                try:
                    conn.sendall(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Connection: close\r\n\r\n"
                    )
                    conn.sendall(self.body)
                except OSError:
                    pass

    def close(self) -> None:
        self.server.close()


def test_g69_over_limit_body_with_length_is_read_with_a_bound(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = count_body_reads(monkeypatch)
    env.model.push(
        Reply(body=padded("far too big", 4 * RESPONSE_LIMIT)), say("recovered fine")
    )
    run = env.chat(["first", "second"])
    assert_clean(run)
    assert ERR_RESP_BIG in run.lines()
    assert "far too big" not in run.out
    assert "recovered fine" in run.out
    assert len(responses) == 2
    assert max(r._gate_bytes for r in responses) <= RESPONSE_LIMIT + 1


def test_g69_over_limit_body_without_length_is_read_with_a_bound(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = CloseDelimitedModel(4 * RESPONSE_LIMIT)
    try:
        env.configure(model_url=f"http://127.0.0.1:{server.port}/v1")
        responses = count_body_reads(monkeypatch)
        run = env.chat(["first", "/list"])
    finally:
        server.close()
    assert_clean(run)
    assert server.requests == 1
    assert ERR_RESP_BIG in run.lines()
    assert "far too big" not in run.out
    assert primary_rows(run.out)
    assert len(responses) == 1
    assert responses[0]._gate_bytes <= RESPONSE_LIMIT + 1
