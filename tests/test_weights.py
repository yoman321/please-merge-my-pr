"""Gates for saved weight edits: C22.

Planned gates 37–40, 71 of plans/chat.md.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    DEFAULT_WEIGHTS,
    ERR_BAD_ARGS,
    WEIGHT_KEYS,
    Env,
    assert_clean,
    call,
    canonical_config,
    compact,
    install_config,
    primary_rows,
    refs,
    say,
)

NEW = {
    "urgency": 0,
    "blocks": 0,
    "risk": 0,
    "due_soon": 0,
    "age": 20,
    "diff": 0,
    "ci": 20,
}
# Default-weight code order: 412, 20, 21, 30. With NEW (T = 40, age and ci 50% each):
# 412 = 25 + 50 = 75, 20 = 25 + 50 = 75 (tie → earlier request, then number: 20
# first), 21 ≈ 71.4, 30 ≈ 50.1.
BEFORE_TOP = [412, 20, 21]
AFTER_TOP = [20, 412, 21]

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture


def weights_call(weights: Any, call_id: str = "w1") -> dict[str, Any]:
    return call((call_id, "set_weights", {"weights": weights}))


def raw_weights_call(raw: str, call_id: str = "w1") -> dict[str, Any]:
    return call((call_id, "set_weights", raw))


# Real GitHub labels and risk-path names can hold spaces, colons, and non-ASCII.
ODD_URGENCY = {"priority: high": 1.0, "needs review": 0.5, "é-urgent": 0.75}
ODD_RISK = {"payments api": ["payments/**"], "team:infra": ["infra/**"]}


def odd_key_config(model_url: str | None) -> str:
    text = canonical_config(model_url=model_url)
    urgency = "".join(f"\n{json.dumps(k)} = {v}" for k, v in ODD_URGENCY.items())
    risk = "".join(f"\n{json.dumps(k)} = {json.dumps(v)}" for k, v in ODD_RISK.items())
    text = text.replace("low = 0.25", "low = 0.25" + urgency, 1)
    text = text.replace(
        'migrations = ["migrations/**"]', 'migrations = ["migrations/**"]' + risk, 1
    )
    return text


def assert_odd_keys_kept(text: str) -> dict[str, Any]:
    saved = tomllib.loads(text)
    for key, value in ODD_URGENCY.items():
        assert saved["urgency_labels"][key] == value
    for key, globs in ODD_RISK.items():
        assert saved["risk_paths"][key] == globs
    return saved


def config_dir_state(env: Env) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in env.config.parent.iterdir()}


# ---- gate 37 -------------------------------------------------------------


def full(**changes: Any) -> dict[str, Any]:
    out: dict[str, Any] = dict(DEFAULT_WEIGHTS)
    for key, value in changes.items():
        if value is None:
            out.pop(key)
        else:
            out[key] = value
    return out


BAD: list[Any] = [
    full(ci=None),
    {**full(), "speed": 1.0},
    {**full(risk=None), "risk_paths": 15.0},
    full(age=-1),
    full(age=-0.0001),
    full(age=100.0001),
    full(age="10"),
    full(age=True),
    full(age=None) | {"age": None},
    full(age=[10]),
    dict.fromkeys(WEIGHT_KEYS, 0),
    [1, 1, 1, 1, 1, 1, 1],
    "all equal",
]
BAD_RAW = [
    '{"weights": {"urgency": 1, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1, "age": 2}}',
    '{"weights": {"urgency": NaN, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1}}',
    '{"weights": {"urgency": Infinity, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1}}',
    '{"weights": {"urgency": -Infinity, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1}}',
    '{"weights": {"urgency": 1e400, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1}}',
    '{"weights": {"urgency": 1, "blocks": 1, "risk": 1, "due_soon": 1, "age": 1, "diff": 1, "ci": 1}, "weights": {}}',
]


def assert_rejected(env: Env, run: Any, before: dict[str, bytes]) -> None:
    assert_clean(run)
    assert ERR_BAD_ARGS in env.model.seen[1].tool_results()["w1"]
    assert "[y/N]" not in run.both
    assert config_dir_state(env) == before


@pytest.mark.parametrize("weights", BAD, ids=[str(i) for i in range(len(BAD))])
def test_g37_bad_weights_are_rejected(env: Env, weights: Any) -> None:
    before = config_dir_state(env)
    env.model.push(weights_call(weights), say("ok"))
    assert_rejected(env, env.chat(["set weights", "y"]), before)


@pytest.mark.parametrize("raw", BAD_RAW, ids=[str(i) for i in range(len(BAD_RAW))])
def test_g37_duplicate_and_non_finite_json_is_rejected(env: Env, raw: str) -> None:
    before = config_dir_state(env)
    env.model.push(raw_weights_call(raw), say("ok"))
    assert_rejected(env, env.chat(["set weights", "y"]), before)


@pytest.mark.parametrize(
    "weights",
    [
        {**dict.fromkeys(WEIGHT_KEYS, 0), "urgency": 100},
        {**dict.fromkeys(WEIGHT_KEYS, 0), "ci": 0.0001},
        dict.fromkeys(WEIGHT_KEYS, 100),
        {
            "urgency": 0.5,
            "blocks": 1.5,
            "risk": 2.5,
            "due_soon": 3.5,
            "age": 4.5,
            "diff": 5.5,
            "ci": 6.5,
        },
    ],
)
def test_g37_boundary_weights_reach_the_prompt(
    env: Env, weights: dict[str, float]
) -> None:
    before = config_dir_state(env)
    env.model.push(weights_call(weights), say("ok"))
    run = env.chat(["set weights", "n"])
    assert_clean(run)
    assert ERR_BAD_ARGS not in env.model.seen[1].tool_results()["w1"]
    assert run.both.count("[y/N]") == 1
    assert config_dir_state(env) == before


# ---- gate 38 -------------------------------------------------------------


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def numbers(line: str) -> set[float]:
    return {round(float(n), 6) for n in NUMBER.findall(line)}


def share_forms(fraction: float) -> set[float]:
    return {
        round(fraction * 100, 6),
        round(fraction, 6),
        round(fraction * 100, 1),
        round(fraction * 100),
    }


def test_g38_preview_shows_values_shares_ranks_and_path(env: Env) -> None:
    env.model.push(
        call(("m1", "move", {"pr": "acme/api#30", "position": "top", "reason": "r"})),
        say("moved"),
        weights_call(NEW),
        say("ok"),
    )
    run = env.chat(["move 30 up", "rebalance", "n"])
    assert_clean(run)
    segment = run.segments()[1]
    preview = (
        segment[: segment.index("[y/N]")] if "[y/N]" in segment else segment + run.err
    )
    assert compact(str(env.config)) in compact(preview + run.err)
    lines = (preview + "\n" + run.err).splitlines()
    for key in WEIGHT_KEYS:
        old, new = DEFAULT_WEIGHTS[key], float(NEW[key])
        old_share, new_share = old / 100.0, new / 40.0
        matching = [line for line in lines if re.search(rf"\b{key}\b", line)]
        assert any(
            round(old, 6) in numbers(line)
            and round(new, 6) in numbers(line)
            and share_forms(old_share) & numbers(line)
            and share_forms(new_share) & numbers(line)
            for line in matching
        ), (key, matching)
    seen = refs(preview + "\n" + run.err)
    wanted = BEFORE_TOP + AFTER_TOP
    it = iter(seen)
    assert all(n in it for n in wanted), (seen, wanted)


def test_g38_preview_with_fewer_than_three_rows(env: Env) -> None:
    for number in (21, 30):
        del env.github.prs[("acme/api", number)]
    env.model.push(weights_call(NEW), say("ok"))
    run = env.chat(["rebalance", "n"])
    assert_clean(run)
    text = run.out + run.err
    seen = refs(text[: text.index("[y/N]")] if "[y/N]" in text else text)
    it = iter(seen)
    assert all(n in it for n in [412, 20, 20, 412]), seen


# ---- gate 39 -------------------------------------------------------------


@pytest.mark.parametrize("answer", ["n", "", "maybe"])
def test_g39_decline_keeps_config_bytes(env: Env, answer: str) -> None:
    before = config_dir_state(env)
    env.model.push(weights_call(NEW), say("ok"))
    run = env.chat(["rebalance", answer, "/list 50"])
    assert_clean(run)
    assert config_dir_state(env) == before
    assert [s for _, s, _ in primary_rows(run.segments()[1])] == [29, 21, 13, 5]


def test_g39_failed_write_keeps_config_usable(env: Env) -> None:
    before = config_dir_state(env)
    directory = env.config.parent
    directory.chmod(0o555)
    try:
        env.model.push(weights_call(NEW), say("ok"))
        run = env.chat(["rebalance", "y", "/list 50"])
    finally:
        directory.chmod(0o755)
    assert_clean(run)
    assert config_dir_state(env) == before
    assert [s for _, s, _ in primary_rows(run.segments()[1])] == [29, 21, 13, 5]
    assert_clean(env.direct(["list"]))


# ---- gate 40 -------------------------------------------------------------


def fd_path(fd: int) -> str:
    if sys.platform == "darwin":
        import fcntl

        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
        return os.fsdecode(raw.split(b"\0", 1)[0])
    return os.readlink(f"/proc/self/fd/{fd}")


def test_g40_approval_backs_up_replaces_and_rescores(env: Env) -> None:
    old_bytes = env.config.read_bytes()
    old_inode = env.config.stat().st_ino
    events: list[tuple[str, str, str]] = []
    real_fsync, real_replace, real_rename = os.fsync, os.replace, os.rename

    def fsync(fd: Any) -> None:
        number = fd if isinstance(fd, int) else fd.fileno()
        events.append(("fsync", os.path.realpath(fd_path(number)), ""))
        real_fsync(fd)

    def replace(src: Any, dst: Any, **kwargs: Any) -> None:
        events.append(("replace", os.path.realpath(src), os.path.realpath(dst)))
        real_replace(src, dst, **kwargs)

    def rename(src: Any, dst: Any, **kwargs: Any) -> None:
        events.append(("replace", os.path.realpath(src), os.path.realpath(dst)))
        real_rename(src, dst, **kwargs)

    env.model.push(
        call(("m1", "move", {"pr": "acme/api#30", "position": "top", "reason": "r"})),
        say("moved"),
        weights_call(NEW),
        say("saved"),
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        patch.setattr(os, "replace", replace)
        patch.setattr(os, "rename", rename)
        run = env.chat(["move 30 up", "rebalance", "y", "/list 50"])
    assert_clean(run)

    config = os.path.realpath(env.config)
    directory = os.path.realpath(env.config.parent)
    backup = env.config.parent / "config.toml.bak"
    assert backup.read_bytes() == old_bytes
    assert sorted(p.name for p in env.config.parent.iterdir()) == [
        "config.toml",
        "config.toml.bak",
    ]
    assert env.config.stat().st_ino != old_inode
    saved = tomllib.loads(env.config.read_text())
    assert {k: float(v) for k, v in saved["weights"].items()} == {
        k: float(v) for k, v in NEW.items()
    }

    swaps = [e for e in events if e[0] == "replace" and e[2] == config]
    assert len(swaps) == 1, events
    swap = events.index(swaps[0])
    temp = swaps[0][1]
    assert os.path.dirname(temp) == directory
    assert ("fsync", temp, "") in events[:swap], events
    assert ("fsync", directory, "") in events[swap + 1 :], events

    rows = primary_rows(run.segments()[2])  # the y answers the prompt
    assert rows[0][0] == 30 and "[moved by AI]" in rows[0][2]
    direct = json.loads(env.direct(["list", "--all", "--json"]).out)
    assert {n: s for n, s, _ in rows} == {
        i["number"]: i["score"] for i in direct["items"]
    }
    assert [n for n, _, _ in rows[1:]] == [
        i["number"] for i in direct["items"] if i["number"] != 30
    ]
    assert {n: s for n, s, _ in rows}[412] == 75


def test_g40_approval_keeps_label_and_path_keys_loadable(env: Env) -> None:
    install_config(env.dirs, odd_key_config(env.model.base_url))
    assert_odd_keys_kept(env.config.read_text())
    env.model.push(weights_call(NEW), say("saved"))
    run = env.chat(["rebalance", "y", "/list 50"])
    assert_clean(run)
    saved = assert_odd_keys_kept(env.config.read_text())
    assert {k: float(v) for k, v in saved["weights"].items()} == {
        k: float(v) for k, v in NEW.items()
    }
    rows = primary_rows(run.segments()[1])  # the y answers the prompt
    assert [n for n, _, _ in rows] == [20, 412, 21, 30]
    direct = env.direct(["list", "--all", "--json"])
    assert_clean(direct)
    assert [i["number"] for i in json.loads(direct.out)["items"]] == [20, 412, 21, 30]


# ---- gate 71: preview rows are code rows, and every line fits 80 columns -

# T = 110. 412: 10/110 * 0.5 → 5. 20: 100/110 * 0.25 + 10/110 * 0.5 → 27.
# 21: 10/110 * 6/14 → 4. 30: ≈ 0. After top three: 20, 412, 21.
W71 = {
    "urgency": 100,
    "blocks": 0,
    "risk": 0,
    "due_soon": 0,
    "age": 10,
    "diff": 0,
    "ci": 0,
}
ROW = re.compile(r"^\s*#(\d+) (\S.*?)   \[score (\d+)\]$")
CONFIG_TAIL = "/please-merge-my-pr/config.toml"


def test_g71_preview_rows_are_code_rows_within_80_columns(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chat_harness import compact, strip_ansi

    root = str(env.dirs["home"])
    pad = 200 - len(root) - 1 - len(CONFIG_TAIL)
    assert 1 <= pad <= 255, pad
    home = env.dirs["home"] / ("p" * pad)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    path = install_config(
        {**env.dirs, "config": home}, canonical_config(model_url=env.model.base_url)
    )
    assert len(str(path)) == 200
    env.model.push(weights_call(W71), say("saved"))
    run = env.chat(["/list", "rebalance", "y", "/list"])
    assert_clean(run)
    segments = run.segments()
    turn = segments[1]
    preview = turn[: turn.index("[y/N]")]
    rows = [
        line.strip() for line in strip_ansi(preview).splitlines() if ROW.match(line)
    ]
    expected = [line.strip() for _, _, line in primary_rows(segments[0])[:3]] + [
        line.strip() for _, _, line in primary_rows(segments[2])[:3]
    ]
    assert rows == expected, (rows, expected)
    found = [(int(m[1]), int(m[3])) for m in map(ROW.match, rows) if m]
    assert found == [(412, 29), (20, 21), (21, 13), (20, 27), (412, 5), (21, 4)]
    assert str(path) in compact(preview)
    for line in strip_ansi(run.out + run.err).splitlines():
        assert len(line) <= 80, (len(line), line)
