"""Gates for generated summaries and the bounded diff: C26.

Planned gates 51–54 of plans/chat.md.
"""

from __future__ import annotations

import json
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    DIFF_LIMIT,
    ERR_REQUESTS,
    ERR_SUMMARY_LIMIT,
    Env,
    assert_clean,
    call,
    say,
    summary_json,
)

SHOW = ("s1", "show", {"pr": "acme/api#412", "summary": True})

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture


def summary_text(env: Env) -> str:
    [request] = env.model.summaries()
    return "\n".join(str(m.get("content") or "") for m in request.messages)


# ---- gate 51: diff ------------------------------------------------------


def diff_world(env: Env, a: str, b: str) -> None:
    pr = env.github.prs[("acme/api", 412)]
    pr.files = [
        ("src/b.py", 1, 0),
        ("uv.lock", 5, 0),
        ("web/package-lock.json", 5, 0),
        ("img/logo.png", 0, 0),
        ("src/a.py", 1, 0),
    ]
    patches = env.github.more("acme/api", 412).patches
    patches["src/a.py"] = a
    patches["src/b.py"] = b
    patches["uv.lock"] = "@@ -1 +1 @@\n+LOCKPATCHMARK"
    patches["web/package-lock.json"] = "@@ -1 +1 @@\n+LOCKPATCHMARK2"
    patches["img/logo.png"] = None


def test_g51_diff_is_sorted_and_skips_lockfiles_and_binaries(env: Env) -> None:
    diff_world(env, "@@ -1 +1 @@\n+ALPHAPATCHMARK", "@@ -1 +1 @@\n+BRAVOPATCHMARK")
    env.model.push(call(SHOW), summary_json(), say("ok"))
    assert_clean(env.chat(["summarize"]))
    text = summary_text(env)
    assert "ALPHAPATCHMARK" in text and "BRAVOPATCHMARK" in text
    assert text.index("ALPHAPATCHMARK") < text.index("BRAVOPATCHMARK")
    assert "LOCKPATCHMARK" not in text
    for key in ("what_changed", "files", "risk_notes", "tests_changed"):
        assert key in text


def test_g51_diff_stops_at_65536_bytes_without_cutting_a_character(env: Env) -> None:
    a = "@@ -1 +1 @@\n+" + "é" * 20_000
    b = "@@ -1 +1 @@\n+" + "ü" * 20_000
    diff_world(env, a, b)
    env.model.push(call(SHOW), summary_json(), say("ok"))
    assert_clean(env.chat(["summarize"]))
    text = summary_text(env)
    assert "�" not in text
    assert text.count("é") == 20_000
    used = len(a.encode()) + 2 * text.count("ü")
    assert used <= DIFF_LIMIT
    assert used >= DIFF_LIMIT - 2_000  # only headers may take the rest
    first = env.model.summaries()[0].body
    env.model.seen.clear()
    env.model.push(call(SHOW), summary_json(), say("ok"))
    assert_clean(env.chat(["summarize"]))
    assert env.model.summaries()[0].body == first


def test_g51_small_diff_is_whole(env: Env) -> None:
    diff_world(env, "@@ -1 +1 @@\n+" + "a" * 1000, "@@ -1 +1 @@\n+" + "b" * 1000)
    env.model.push(call(SHOW), summary_json(), say("ok"))
    assert_clean(env.chat(["summarize"]))
    text = summary_text(env)
    assert "a" * 1000 in text and "b" * 1000 in text


# ---- gate 52: schema ------------------------------------------------------


BAD_SUMMARIES: list[tuple[str, Any]] = [
    ("tool call", call(("x", "list_queue", {"limit": 1}))),
    ("missing field", summary_json(tests_changed=None)),
    (
        "extra field",
        say(
            json.dumps(
                {
                    **json.loads(summary_json()["choices"][0]["message"]["content"]),
                    "extra": "x",
                }
            )
        ),
    ),
    ("wrong type", summary_json(files=["auth/session.py"])),
    ("number", summary_json(risk_notes=3)),
    ("overlong", summary_json(what_changed="é" * 1001)),
    ("not json", say("It refactors the session store.")),
    ("array", say(json.dumps([1, 2]))),
    ("empty", say("")),
]


@pytest.mark.parametrize(
    "bad", [b[1] for b in BAD_SUMMARIES], ids=[b[0] for b in BAD_SUMMARIES]
)
def test_g52_invalid_summary_twice_is_a_local_error(env: Env, bad: Any) -> None:
    env.model.push(call(SHOW), bad, bad, say("final"))
    run = env.chat(["summarize", "/list"])
    assert_clean(run)
    assert len(env.model.summaries()) == 2
    result = json.loads(env.model.conversational()[1].tool_results()["s1"])
    assert "Refactors the session store." not in json.dumps(result)
    for line in run.out.splitlines():
        if "session store" in line:
            assert line.lstrip().startswith("AI:"), line


def test_g52_valid_summary_at_the_limit_is_accepted(env: Env) -> None:
    long = "é" * 1000
    env.model.push(call(SHOW), summary_json(what_changed=long), say("final"))
    run = env.chat(["summarize"])
    assert_clean(run)
    assert len(env.model.summaries()) == 1
    assert long in env.model.conversational()[1].tool_results()["s1"]
    for line in run.out.splitlines():
        if "éééé" in line:
            assert line.lstrip().startswith("AI:"), line


# ---- gate 53: one repair --------------------------------------------------


def test_g53_one_repair_then_success(env: Env) -> None:
    env.model.push(
        call(SHOW),
        say("not json"),
        summary_json(what_changed="Fixed on repair."),
        say("final"),
    )
    run = env.chat(["summarize"])
    assert_clean(run)
    summaries = env.model.summaries()
    assert len(summaries) == 2
    for request in summaries:
        assert "tools" not in request.json
    assert (
        len(summaries[1].messages) > len(summaries[0].messages)
        or summaries[1].body != summaries[0].body
    )
    assert "Fixed on repair." in env.model.conversational()[1].tool_results()["s1"]
    assert len(env.model.seen) == 4


def test_g53_no_repair_when_the_turn_budget_is_spent(env: Env) -> None:
    for i in range(1, 7):
        env.model.push(call((f"l{i}", "list_queue", {"limit": 1})))
    env.model.push(call(SHOW), say("not json"), summary_json(), say("never"))
    run = env.chat(["go", "/list"])
    assert_clean(run)
    assert len(env.model.seen) == 8
    assert len(env.model.summaries()) == 1
    assert ERR_REQUESTS in run.both


# ---- gate 54: one summary per turn ----------------------------------------


def test_g54_second_summary_in_a_turn_makes_no_call(env: Env) -> None:
    env.model.push(
        call(SHOW, ("s2", "show", {"pr": "acme/api#20", "summary": True})),
        summary_json(),
        call(("s3", "show", {"pr": "acme/api#21", "summary": True})),
        say("final"),
        call(("s4", "show", {"pr": "acme/api#21", "summary": True})),
        summary_json(),
        say("next turn"),
    )
    run = env.chat(["summarize two", "summarize again"])
    assert_clean(run)
    assert len(env.model.summaries()) == 2
    turn_one = env.model.conversational()
    assert ERR_SUMMARY_LIMIT in turn_one[1].tool_results()["s2"]
    assert ERR_SUMMARY_LIMIT not in turn_one[1].tool_results()["s1"]
    assert ERR_SUMMARY_LIMIT in turn_one[2].tool_results()["s3"]
    assert ERR_SUMMARY_LIMIT not in turn_one[4].tool_results()["s4"]
    assert "next turn" in run.out
