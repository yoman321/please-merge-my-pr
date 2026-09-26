"""Gates for setup and config: C23.

Planned gates 41–44, 72, 73 of plans/chat.md.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import chat_harness
import pytest
from chat_harness import (
    KEY_VALUE,
    TOKEN_VALUE,
    WEIGHT_KEYS,
    Env,
    assert_clean,
    canonical_config,
    compact,
    config_path,
    env_setup,
    install_config,
    queue_world,
    run_main,
    say,
)
from conftest import API, guard

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture

SECTIONS = {
    "github",
    "model",
    "weights",
    "scoring",
    "urgency_labels",
    "risk_paths",
    "files",
    "display",
}

# ---- gate 41: init -------------------------------------------------------


def answers(confirm: str, count: int = 40) -> list[Any]:
    """Answer each init question from the text of the prompt that asked it."""

    asked: list[str] = []

    def reply(printed: str) -> str:
        last = printed.rstrip("\n").rsplit("\n", 1)[-1].lower()
        if "model" in last:
            return "n" if "[y/n]" in last else ""
        if "[y/n]" in last:
            return confirm
        if "repo" in last:
            asked.append(last)
            return "acme/api" if len(asked) == 1 else ""
        return ""

    return [reply] * count


@pytest.fixture
def fresh(
    isolated: Mapping[str, Path], monkeypatch: pytest.MonkeyPatch
) -> Mapping[str, Path]:
    env_setup(monkeypatch)
    return isolated


def test_g41_init_previews_once_and_writes_after_yes(fresh: Mapping[str, Path]) -> None:
    path = config_path(fresh)
    run = run_main(["init"], queue_world(), answers("y"))
    assert_clean(run)
    assert path.exists()
    text = path.read_text()
    parsed = tomllib.loads(text)
    assert "acme/api" in parsed["github"]["repos"]
    assert set(parsed) <= SECTIONS
    shown = compact(run.both)
    assert compact(text) in shown
    assert shown.count(compact(text)) == 1
    assert str(path) in run.both
    assert run.both.count("[y/N]") >= 1
    assert TOKEN_VALUE not in text and KEY_VALUE not in text
    assert_clean(run_main(["config", "show"], queue_world()))


@pytest.mark.parametrize("confirm", ["n", "", "sure"])
def test_g41_init_decline_writes_nothing(
    fresh: Mapping[str, Path], confirm: str
) -> None:
    run = run_main(["init"], queue_world(), answers(confirm))
    assert not run.crash, run.crash
    assert run.both.count("[y/N]") >= 1  # the preview and prompt were shown
    assert not config_path(fresh).exists()
    assert list(fresh["config"].rglob("*")) in ([], [config_path(fresh).parent])


def test_g41_init_refuses_to_overwrite(fresh: Mapping[str, Path]) -> None:
    path = install_config(fresh, "# mine\n")
    run = run_main(["init"], queue_world(), answers("y"))
    assert not run.crash, run.crash
    assert run.code != 0
    assert path.read_bytes() == b"# mine\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["config.toml"]
    path.unlink()
    assert_clean(run_main(["init"], queue_world(), answers("y")))
    assert path.read_bytes() != b"# mine\n"  # without a file, init does write


# ---- gate 42: config commands --------------------------------------------


def test_g42_config_path(env: Env) -> None:
    run = env.direct(["config", "path"])
    assert_clean(run)
    assert run.out.strip() == str(env.config)


def test_g42_config_path_default_without_xdg(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
    run = env.direct(["config", "path"])
    assert_clean(run)
    assert run.out.strip() == str(
        env.dirs["home"] / ".config" / "please-merge-my-pr" / "config.toml"
    )


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


def test_g42_config_show_is_canonical_and_redacted(env: Env) -> None:
    run = env.direct(["config", "show"])
    assert_clean(run)
    shown = tomllib.loads(run.out)
    assert set(shown) == SECTIONS
    assert set(shown["weights"]) == set(WEIGHT_KEYS)
    assert shown["github"]["repos"] == ["acme/api", "acme/web"]
    assert shown["display"]["limit"] == 3
    assert TOKEN_VALUE not in run.both and KEY_VALUE not in run.both


SETS = [
    ("display.limit", "5", ("display", "limit"), 5),
    ("weights.age", "12.5", ("weights", "age"), 12.5),
    (
        "github.web_url",
        '"https://ghe.example.com"',
        ("github", "web_url"),
        "https://ghe.example.com",
    ),
    ("risk_paths.infra", '["infra/**"]', ("risk_paths", "infra"), ["infra/**"]),
    (
        "model.base_url",
        '"http://127.0.0.1:8080/v1"',
        ("model", "base_url"),
        "http://127.0.0.1:8080/v1",
    ),
    ("urgency_labels.high", "0.9", ("urgency_labels", "high"), 0.9),
    ("scoring.blocked_people_cap", "4.0", ("scoring", "blocked_people_cap"), 4.0),
]


@pytest.mark.parametrize(
    ("key", "literal", "where", "value"), SETS, ids=[s[0] for s in SETS]
)
def test_g42_config_set_writes_atomically(
    env: Env, key: str, literal: str, where: tuple[str, str], value: Any
) -> None:
    before = tomllib.loads(env.config.read_text())
    inode = env.config.stat().st_ino
    run = env.direct(["config", "set", key, literal])
    assert_clean(run)
    after = tomllib.loads(env.config.read_text())
    assert after[where[0]][where[1]] == value
    before.setdefault(where[0], {})[where[1]] = value
    assert after == before
    assert env.config.stat().st_ino != inode
    assert not [
        p
        for p in env.config.parent.iterdir()
        if p.name not in {"config.toml", "config.toml.bak"}
    ]


BAD_SETS = [
    ("display.limit", "0", "display.limit"),
    ("display.limit", "51", "display.limit"),
    ("display.limit", '"5"', "display.limit"),
    ("display.limit", "not toml", "display.limit"),
    ("display.nope", "1", "display.nope"),
    ("weights.age", "-1", "weights.age"),
    ("weights.age", "nan", "weights.age"),
    ("weights.speed", "1", "weights.speed"),
    ("model.base_url", '"http://localhost:8080/v1"', "model.base_url"),
    ("github.api_url", '"http://api.github.com"', "github.api_url"),
    ("github.token_env", '"1BAD"', "github.token_env"),
    ("github.repos", '["acme/api", "acme/api"]', "github.repos"),
    ("urgency_labels.high", "1.5", "urgency_labels.high"),
    ("files.lockfiles", '["/abs/uv.lock"]', "files.lockfiles"),
]


@pytest.mark.parametrize(
    ("key", "literal", "named"), BAD_SETS, ids=[f"{k}={v}" for k, v, _ in BAD_SETS]
)
def test_g42_config_set_rejects_and_keeps_bytes(
    env: Env, key: str, literal: str, named: str
) -> None:
    before = env.config.read_bytes()
    run = env.direct(["config", "set", key, literal])
    assert not run.crash, run.crash
    assert run.code != 0
    assert named in run.err
    assert env.config.read_bytes() == before


def editor(env: Env, monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    source = env.dirs["home"] / "edited.toml"
    source.write_text(text)
    script = env.dirs["bin"] / "fake-editor"
    script.write_text(f'#!/bin/sh\n/bin/cat "{source}" > "$1"\n')
    script.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(script))
    monkeypatch.setenv("VISUAL", str(script))


def test_g42_config_edit_validates_then_writes_atomically(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor(
        env,
        monkeypatch,
        canonical_config(model_url=env.model.base_url, display_limit=7),
    )
    inode = env.config.stat().st_ino
    run = env.direct(["config", "edit"], tty_in=True, tty_out=True)
    assert_clean(run)
    assert tomllib.loads(env.config.read_text())["display"]["limit"] == 7
    assert env.config.stat().st_ino != inode


def test_g42_config_edit_rejects_invalid_result(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    editor(
        env,
        monkeypatch,
        canonical_config(model_url=env.model.base_url, display_limit=0),
    )
    before = env.config.read_bytes()
    run = env.direct(["config", "edit"], tty_in=True, tty_out=True)
    assert not run.crash, run.crash
    assert run.code != 0
    assert "display.limit" in run.err
    assert env.config.read_bytes() == before


# ---- gate 43: invalid config ------------------------------------------


def edit_toml(text: str, section: str | None, key: str, literal: str | None) -> str:
    """Set (or with None, delete) `key` in `[section]`; None section = top level."""
    lines = text.splitlines()
    start = 0
    if section is not None:
        start = lines.index(f"[{section}]") + 1
    end = next(
        (i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines)
    )
    for i in range(start, end):
        if re.match(rf"^{re.escape(key)}\s*=", lines[i]):
            if literal is None:
                del lines[i]
            else:
                lines[i] = f"{key} = {literal}"
            return "\n".join(lines) + "\n"
    if literal is not None:
        lines.insert(start, f"{key} = {literal}")
    return "\n".join(lines) + "\n"


INVALID = [
    ("display", "limit", "0", "display.limit"),
    ("display", "limit", "51", "display.limit"),
    ("display", "limit", '"3"', "display.limit"),
    ("display", "foo", "1", "display.foo"),
    ("weights", "age", "-1.0", "weights.age"),
    ("weights", "age", "nan", "weights.age"),
    ("weights", "age", "inf", "weights.age"),
    ("weights", "age", "100.5", "weights.age"),
    ("weights", "speed", "1.0", "weights.speed"),
    ("weights", "risk_paths", "15.0", "weights.risk"),
    ("github", "api_url", '"http://api.fake-github.test"', "github.api_url"),
    ("github", "api_url", '"https://u:p@api.fake-github.test"', "github.api_url"),
    ("github", "api_url", '"https://api.fake-github.test/?a=1"', "github.api_url"),
    ("github", "web_url", '"https://github.com/#x"', "github.web_url"),
    ("github", "web_url", '"http://github.com"', "github.web_url"),
    ("github", "token_env", '"1BAD"', "github.token_env"),
    ("github", "token_env", '"BAD-NAME"', "github.token_env"),
    ("github", "repos", '["acme/api", "acme/api"]', "github.repos"),
    ("github", "repos", '["acme"]', "github.repos"),
    ("model", "api_key_env", '"has space"', "model.api_key_env"),
    ("model", "name", '""', "model.name"),
    ("model", "base_url", '"http://localhost/v1"', "model.base_url"),
    ("scoring", "age_cap_days", "0.0", "scoring.age_cap_days"),
    ("scoring", "diff_cap_lines", "-5.0", "scoring.diff_cap_lines"),
    ("scoring", "due_horizon_days", "inf", "scoring.due_horizon_days"),
    ("scoring", "blocked_people_cap", "0.0", "scoring.blocked_people_cap"),
    ("urgency_labels", "high", "1.5", "urgency_labels.high"),
    ("urgency_labels", "low", "-0.1", "urgency_labels.low"),
    ("risk_paths", "auth", '["auth/**", "auth/**"]', "risk_paths.auth"),
    ("risk_paths", "auth", '[""]', "risk_paths.auth"),
    ("risk_paths", "auth", '["/abs/**"]', "risk_paths.auth"),
    ("risk_paths", "auth", '"auth/**"', "risk_paths.auth"),
    ("files", "lockfiles", '["", "uv.lock"]', "files.lockfiles"),
    (None, "surprise", "1", "surprise"),
    (None, "repos", '["acme/api"]', "repos"),
]


def all_zero(text: str) -> str:
    for key in WEIGHT_KEYS:
        text = edit_toml(text, "weights", key, "0.0")
    return text


@pytest.mark.parametrize(
    ("section", "key", "literal", "named"),
    INVALID,
    ids=[f"{s}.{k}={v}" for s, k, v, _ in INVALID],
)
def test_g43_invalid_config_fails_first_and_names_the_key(
    env: Env, section: str | None, key: str, literal: str, named: str
) -> None:
    text = canonical_config(model_url=env.model.base_url)
    install_config(env.dirs, edit_toml(text, section, key, literal))
    check_invalid(env, named)


def check_invalid(env: Env, named: str) -> None:
    for argv in (
        ["list"],
        ["why", "acme/api#412"],
        ["watch"],
        ["label", "acme/api#412", "--add", "bug"],
    ):
        with guard(network=True, writes=True) as violations:
            run = env.direct(argv, ["y"], tty_in=True)
        assert violations == []
        assert not run.crash, run.crash
        assert run.code != 0, argv
        assert named in run.err, (argv, run.err)
    with guard(network=True, writes=True) as violations:
        run = env.chat(["hello"])
    assert violations == []
    assert run.code != 0
    assert named in run.err
    assert env.github.requests == []
    assert env.model.seen == []


def test_g43_all_zero_weights_fail(env: Env) -> None:
    install_config(env.dirs, all_zero(canonical_config(model_url=env.model.base_url)))
    check_invalid(env, "weights")


def test_g43_bad_toml_fails(env: Env) -> None:
    install_config(env.dirs, "[github\napi_url = 3\n")
    for argv in (["list"], ["config", "show"]):
        run = env.direct(argv)
        assert not run.crash, run.crash
        assert run.code != 0
    assert env.github.requests == []


# ---- gate 44: legacy aliases -------------------------------------------


LEGACY = f"""repos = ["acme/api", "acme/web"]
lockfiles = ["**/uv.lock", "**/package-lock.json"]

[github]
api_url = "{API}"

[weights]
urgency = 30.0
blocks = 25.0
risk_paths = 15.0
due_soon = 10.0
age = 10.0
diff_size = 5.0
ci_state = 5.0

[scoring]
age_cap_days = 14.0
diff_cap_lines = 500.0

[risk_paths]
auth = ["auth/**"]
billing = ["billing/**"]
migrations = ["migrations/**"]
"""


def test_g44_legacy_aliases_load_and_the_next_write_is_canonical(env: Env) -> None:
    canonical = json.loads(env.direct(["list", "--all", "--json"]).out)
    install_config(env.dirs, LEGACY)
    legacy = env.direct(["list", "--all", "--json"])
    assert_clean(legacy)
    assert [(i["number"], i["score"]) for i in json.loads(legacy.out)["items"]] == [
        (i["number"], i["score"]) for i in canonical["items"]
    ]
    assert_clean(env.direct(["config", "set", "display.limit", "4"]))
    text = env.config.read_text()
    saved = tomllib.loads(text)
    assert "repos" not in saved and "lockfiles" not in saved
    assert saved["github"]["repos"] == ["acme/api", "acme/web"]
    assert saved["files"]["lockfiles"] == ["**/uv.lock", "**/package-lock.json"]
    assert set(saved["weights"]) == set(WEIGHT_KEYS)
    assert saved["weights"]["risk"] == 15.0
    assert saved["weights"]["diff"] == 5.0
    assert saved["weights"]["ci"] == 5.0
    assert saved["display"]["limit"] == 4
    for alias in ("risk_paths =", "diff_size", "ci_state"):
        assert alias not in text


@pytest.mark.parametrize(
    ("canonical", "alias", "named"),
    [
        ("risk", "risk_paths", "weights.risk"),
        ("diff", "diff_size", "weights.diff"),
        ("ci", "ci_state", "weights.ci"),
    ],
)
def test_g44_mixed_aliases_fail(
    env: Env, canonical: str, alias: str, named: str
) -> None:
    text = canonical_config(model_url=env.model.base_url)
    install_config(env.dirs, edit_toml(text, "weights", alias, "5.0"))
    check_invalid(env, named)


def test_g44_mixed_top_level_and_section_fail(env: Env) -> None:
    text = canonical_config(model_url=env.model.base_url)
    install_config(env.dirs, 'lockfiles = ["**/uv.lock"]\n' + text)
    check_invalid(env, "lockfiles")


@pytest.mark.parametrize(
    "argv",
    [
        ["config", "set", "weights.age", "12.5"],
        ["config", "set", "display.limit", "5"],
        ["config", "show"],
    ],
    ids=["set_weights_age", "set_display_limit", "show"],
)
def test_g42_config_commands_keep_label_and_path_keys_loadable(
    env: Env, argv: list[str]
) -> None:
    install_config(env.dirs, odd_key_config(env.model.base_url))
    assert_odd_keys_kept(env.config.read_text())
    run = env.direct(argv)
    assert_clean(run)
    written = run.out if argv[1] == "show" else env.config.read_text()
    assert_odd_keys_kept(written)
    after = env.direct(["list", "--json"])
    assert_clean(after)


# ---- gate 72: config set can start the model section ---------------------

MODEL_KEYS = ["base_url", "name", "api_key_env"]


def model_literal(env: Env, name: str) -> tuple[str, str]:
    value = {
        "base_url": env.model.base_url,
        "name": "fake-model-7",
        "api_key_env": "MODEL_API_KEY",
    }[name]
    return json.dumps(value), value


def without_model(env: Env) -> Path:
    path = install_config(env.dirs, canonical_config())
    assert "model" not in tomllib.loads(path.read_text())
    return path


@pytest.mark.parametrize("name", MODEL_KEYS)
def test_g72_config_set_one_model_key_without_a_model_section(
    env: Env, name: str
) -> None:
    from chat_harness import ERR_NO_MODEL

    path = without_model(env)
    before = tomllib.loads(path.read_text())
    literal, value = model_literal(env, name)
    run = env.direct(["config", "set", f"model.{name}", literal])
    assert_clean(run)
    after = tomllib.loads(path.read_text())
    assert after["model"] == {name: value}
    assert {k: v for k, v in after.items() if k != "model"} == before
    assert_clean(env.direct(["config", "show"]))
    # Human decision 2026-09-25: a partial model section is valid, and chat
    # treats it as not configured until base_url and name are both set.
    chat_run = env.chat(["hello", "/list"])
    assert_clean(chat_run)
    assert ERR_NO_MODEL in chat_run.lines()
    assert env.model.seen == []


def test_g72_config_set_builds_a_working_model_section(env: Env) -> None:
    path = without_model(env)
    for name in MODEL_KEYS:
        literal, _ = model_literal(env, name)
        assert_clean(env.direct(["config", "set", f"model.{name}", literal]))
    model_table = tomllib.loads(path.read_text())["model"]
    assert model_table == {name: model_literal(env, name)[1] for name in MODEL_KEYS}
    env.model.push(say("hello back"))
    run = env.chat(["hello"])
    assert_clean(run)
    assert len(env.model.seen) == 1
    assert "hello back" in run.out


@pytest.mark.parametrize(
    ("key", "literal"),
    [
        ("model.bogus", '"x"'),
        ("model.base_url", '"http://localhost:8080/v1"'),
        ("model.name", '""'),
    ],
)
def test_g72_bad_model_keys_still_fail_without_a_model_section(
    env: Env, key: str, literal: str
) -> None:
    path = without_model(env)
    before = path.read_bytes()
    run = env.direct(["config", "set", key, literal])
    assert not run.crash, run.crash
    assert run.code != 0
    assert key in run.err
    assert path.read_bytes() == before


# ---- gate 73: init reports a bad answer without a traceback --------------


def init_answers(repo: str, model_name: str | None) -> list[Any]:
    """repo: the first repository typed. model_name None: no model."""
    asked: list[str] = []
    seen = [0]

    def reply(printed: str) -> str:
        last = printed[seen[0] :].rstrip("\n").rsplit("\n", 1)[-1].lower()
        seen[0] = len(printed)
        if "[y/n]" in last and "model" in last:
            return "n" if model_name is None else "y"
        if "[y/n]" in last:
            return "y"
        if "repo" in last:
            asked.append(last)
            return repo if len(asked) == 1 else ""
        if "model" in last and "url" in last:
            return "https://models.example.test/v1"
        if "model" in last and "name" in last:
            return model_name or ""
        return ""

    return [reply] * 40


@pytest.mark.parametrize(
    ("repo", "model_name", "key"),
    [("acme", None, "github.repos"), ("acme/api", "   ", "model.name")],
    ids=["repo_without_owner", "blank_model_name"],
)
def test_g73_init_bad_answer_prints_the_key_and_exits_2(
    fresh: Mapping[str, Path], repo: str, model_name: str | None, key: str
) -> None:
    run = run_main(["init"], queue_world(), init_answers(repo, model_name))
    assert_clean(run, code=2)
    assert f"invalid config: {key}" in run.both
    assert not config_path(fresh).exists()
    assert [p for p in fresh["config"].rglob("*") if p.is_file()] == []
