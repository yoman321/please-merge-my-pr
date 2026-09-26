"""Gates for session moves: C10–C12.

Planned gates 18–20, 66, 70 of plans/chat.md.
"""

from __future__ import annotations

import json
import re
from typing import Any

import chat_harness
from chat_harness import (
    ERR_BAD_ARGS,
    ERR_MOVES,
    Env,
    assert_clean,
    call,
    future,
    primary_rows,
    say,
    state_db,
)

CODE_ORDER = [412, 20, 21, 30]

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture


def move(
    call_id: str, pr: int, reason: str = "because", **placement: Any
) -> tuple[str, str, Any]:
    return (call_id, "move", {"pr": f"acme/api#{pr}", "reason": reason, **placement})


def order(segment: str) -> list[int]:
    return [n for n, _, _ in primary_rows(segment)]


def scores(segment: str) -> dict[int, int]:
    return {n: s for n, s, _ in primary_rows(segment)}


# ---- gate 18 -------------------------------------------------------------


def test_g18_three_moves_per_turn_then_the_fourth_fails(env: Env) -> None:
    env.model.push(
        call(
            move("m1", 30, position="top"),
            move("m2", 21, position="top"),
            move("m3", 412, position="bottom"),
            move("m4", 20, position="top"),
        ),
        say("moved"),
        call(move("n1", 20, position="top")),
        say("moved again"),
    )
    run = env.chat(["/list 50", "shuffle", "/list 50", "one more", "/list 50"])
    assert_clean(run)
    results = env.model.seen[1].tool_results()
    for call_id in ("m1", "m2", "m3"):
        assert ERR_MOVES not in results[call_id]
    assert ERR_MOVES in results["m4"]
    segments = run.segments()
    assert order(segments[0]) == CODE_ORDER
    assert order(segments[2]) == [21, 30, 20, 412]
    assert ERR_MOVES not in env.model.seen[3].tool_results()["n1"]
    assert order(segments[4]) == [20, 21, 30, 412]


def test_g18_moves_across_requests_share_the_cap(env: Env) -> None:
    env.model.push(
        call(move("m1", 30, position="top")),
        call(move("m2", 21, position="top"), move("bad", 20, position="middle")),
        call(move("m3", 412, position="bottom")),
        call(move("m4", 20, position="top")),
        say("done"),
    )
    run = env.chat(["shuffle", "/list 50"])
    assert_clean(run)
    assert ERR_BAD_ARGS in env.model.seen[2].tool_results()["bad"]
    assert ERR_MOVES not in env.model.seen[3].tool_results()["m3"]
    assert ERR_MOVES in env.model.seen[4].tool_results()["m4"]
    assert order(run.segments()[1]) == [21, 30, 20, 412]


# ---- gate 19 -------------------------------------------------------------


def test_g19_move_changes_order_only(env: Env) -> None:
    env.model.push(
        call(move("m1", 30, reason="tiny and quick to review", before="acme/api#20")),
        say("ok"),
    )
    run = env.chat(["/list 50", "put 30 before 20", "/list 50"])
    assert_clean(run)
    before, after = run.segments()[0], run.segments()[2]
    assert order(after) == [412, 30, 20, 21]
    assert scores(after) == scores(before)
    assert sorted(order(after)) == sorted(CODE_ORDER)
    lines = after.splitlines()
    for number, _, line in primary_rows(after):
        if number == 30:
            assert "[moved by AI]" in line
            follow = lines[lines.index(line) + 1]
            assert follow.lstrip().startswith("AI:")
            assert "tiny and quick to review" in follow
        else:
            assert "[moved by AI]" not in line
    assert "[moved by AI]" not in before


def test_g19_after_and_bottom_placements(env: Env) -> None:
    env.model.push(
        call(move("m1", 412, after="acme/api#21"), move("m2", 20, position="bottom")),
        say("ok"),
    )
    run = env.chat(["rearrange", "/list 50"])
    assert_clean(run)
    assert order(run.segments()[1]) == [21, 412, 30, 20]


def test_g19_overlay_dies_with_the_process(env: Env) -> None:
    env.model.push(call(move("m1", 30, position="top")), say("ok"))
    assert_clean(env.chat(["move 30"]))
    fresh = env.chat(["/list 50"])
    assert_clean(fresh)
    assert order(fresh.segments()[0]) == CODE_ORDER
    assert "[moved by AI]" not in fresh.out
    direct = env.direct(["list", "--limit", "50"], tty_out=True)
    assert fresh.segments()[0] == direct.out


# ---- gate 20 -------------------------------------------------------------


def test_g20_reset_view_restores_code_order_and_keeps_saved_state(env: Env) -> None:
    assert_clean(env.direct(["rules", "add", "acme/api", "--add", "bug"]))
    rules_before = env.direct(["rules", "list"]).out
    config_before = env.config.read_bytes()
    env.model.push(
        call(move("m1", 30, position="top"), move("m2", 21, position="top")),
        say("ok"),
    )
    run = env.chat(
        ["/hide acme/api#20", "shuffle", "/list 50", "/reset-view", "/list 50"]
    )
    assert_clean(run)
    segments = run.segments()
    assert order(segments[2]) == [21, 30, 412]
    assert order(segments[4]) == [412, 21, 30]
    assert "[moved by AI]" not in segments[4]
    assert "AI:" not in segments[4]
    assert scores(segments[4]) == scores(segments[2])
    assert env.config.read_bytes() == config_before
    assert env.direct(["rules", "list"]).out == rules_before
    direct = env.direct(["list", "--limit", "50"], tty_out=True)
    assert segments[4] == direct.out
    assert 20 not in order(direct.out)
    assert env.github.writes == []
    assert state_db(env.dirs).exists()


# ---- gate 66: bad move targets fail and cost nothing ---------------------


def bad_moves() -> dict[str, Any]:
    """#20 is hidden, #21 is snoozed, #999 does not exist."""
    return call(
        move("x1", 30, before="acme/api#30"),
        move("x2", 30, after="acme/api#30"),
        move("x3", 412, after="acme/api#20"),
        move("x4", 412, before="acme/api#21"),
        move("x5", 412, after="acme/api#999"),
    )


def hide_and_snooze() -> list[str]:
    return ["/hide acme/api#20", f"/snooze acme/api#21 {future(3600)}"]


def test_g66_bad_move_targets_fail_and_leave_order(env: Env) -> None:
    env.model.push(
        bad_moves(),
        say("done"),
        call(move("g1", 30, position="top")),
        say("ok"),
    )
    run = env.chat([*hide_and_snooze(), "bad moves", "/list 50", "good", "/list 50"])
    assert_clean(run)
    results = env.model.seen[1].tool_results()
    success = env.model.seen[3].tool_results()["g1"]
    assert ERR_MOVES not in success
    for call_id in ("x1", "x2"):
        assert ERR_BAD_ARGS in results[call_id], results[call_id]
    for call_id in ("x3", "x4", "x5"):
        assert results[call_id] != success, (call_id, results[call_id])
        assert ERR_MOVES not in results[call_id]
    segments = run.segments()
    after_bad = segments[3]
    assert order(after_bad) == [412, 30]
    assert "[moved by AI]" not in after_bad
    assert "AI:" not in after_bad
    assert order(segments[5]) == [30, 412]  # a real move still works


def test_g66_bad_move_targets_do_not_use_a_move(env: Env) -> None:
    env.model.push(
        bad_moves(),
        call(
            move("s1", 30, position="top"),
            move("s2", 412, position="top"),
            move("s3", 30, position="top"),
        ),
        say("done"),
    )
    run = env.chat([*hide_and_snooze(), "shuffle", "/list 50"])
    assert_clean(run)
    assert len(env.model.seen) == 3
    results = env.model.seen[2].tool_results()
    for call_id in ("s1", "s2", "s3"):
        assert ERR_MOVES not in results[call_id], (call_id, results[call_id])
    assert results["s1"] == results["s2"] == results["s3"]
    listed = run.segments()[3]
    assert order(listed) == [30, 412]
    assert "[moved by AI]" in primary_rows(listed)[0][2]


# ---- gate 70: /list shows a move from below the display limit ------------


def queue_order(result: str) -> list[int]:
    """PR numbers in a list_queue result, in the order they appear."""
    found: list[int] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            number = value.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                found.append(number)
                return
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            found.extend(int(n) for n in re.findall(r"acme/api#(\d+)", value))

    walk(json.loads(result))
    return found


def test_g70_list_shows_a_pr_moved_up_from_below_the_limit(env: Env) -> None:
    env.model.push(
        call(move("m1", 30, reason="quick fix", position="top")),
        say("moved"),
        call(("q1", "list_queue", {"limit": 3})),
        say("listed"),
    )
    run = env.chat(["move 30 up", "/list", "what is on top?"])
    assert_clean(run)
    shown = run.segments()[1]
    assert order(shown) == [30, 412, 20]  # display.limit is 3; #30 was 4th
    assert "[moved by AI]" in primary_rows(shown)[0][2]
    assert queue_order(env.model.seen[3].tool_results()["q1"]) == order(shown)
