"""Gates for module boundaries and the declared surface.

Planned gates 61 and 62 of plans/chat.md.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from collections.abc import Mapping
from pathlib import Path

import chat_harness
from chat_harness import (
    DIRECT_COMMANDS,
    SLASH_COMMANDS,
    TOOLS,
    Env,
    assert_clean,
    say,
)
from conftest import REPO_ROOT

env = chat_harness.env  # fixture
model = chat_harness.model  # fixture

SRC = REPO_ROOT / "src" / "please_merge_my_pr"
CHAT = "please_merge_my_pr.chat"
KEPT_OUT = (
    ["scoring.py", "store.py", "queue.py", "events.py", "config.py"]
    + [str(p.relative_to(SRC)) for p in sorted((SRC / "github").glob("*.py"))]
    + [str(p.relative_to(SRC)) for p in sorted((SRC / "signals").glob("*.py"))]
    + [str(p.relative_to(SRC)) for p in sorted((SRC / "ingest").glob("*.py"))]
)


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    package = "please_merge_my_pr." + ".".join(path.relative_to(SRC).parent.parts)
    package = package.rstrip(".")
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if (
                name in ("import_module", "__import__")
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                found.add(str(node.args[0].value))
    return found


# ---- gate 61 -------------------------------------------------------------


def test_g61_chat_is_not_imported_by_core_modules() -> None:
    assert (SRC / "chat.py").exists(), "src/please_merge_my_pr/chat.py is missing"
    offenders = {}
    for name in KEPT_OUT:
        path = SRC / name
        if not path.exists():
            continue
        bad = sorted(m for m in imports(path) if m == CHAT or m.startswith(CHAT + "."))
        if bad:
            offenders[name] = bad
    assert offenders == {}


def test_g61_direct_reads_do_not_load_chat(isolated: Mapping[str, Path]) -> None:
    script = (
        "import json, sys\n"
        "from please_merge_my_pr.cli import main\n"
        "main(['list', '--demo'])\n"
        "main(['why', '1', '--demo'])\n"
        "main(['show', '1', '--demo'])\n"
        f"loaded = {CHAT!r} in sys.modules\n"
        "main(['watch', '--demo'])\n"
        f"loaded = loaded or {CHAT!r} in sys.modules\n"
        "print(json.dumps({'loaded': loaded}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == {"loaded": False}
    assert (SRC / "chat.py").exists()


# ---- gate 62 -------------------------------------------------------------


def choices(text: str) -> set[str]:
    match = re.search(r"\{([a-z][a-z0-9_-]*(?:,[a-z][a-z0-9_-]*)+)\}", text)
    assert match, text
    return set(match.group(1).split(","))


def test_g62_declared_subcommands_only(env: Env, built_wheel: Path) -> None:
    top = env.direct(["--help"])
    assert_clean(top)
    assert choices(top.out) == DIRECT_COMMANDS
    config = env.direct(["config", "--help"])
    assert_clean(config)
    assert choices(config.out) == {"show", "path", "set", "edit"}
    rules = env.direct(["rules", "--help"])
    assert_clean(rules)
    assert choices(rules.out) == {"add", "list", "rm"}
    assert_no_runtime_dependencies(built_wheel)


def test_g62_declared_slash_commands_only(env: Env) -> None:
    run = env.chat(["/help"])
    assert_clean(run)
    shown = set(re.findall(r"(?<![\w/])/([a-z][a-z-]*)", run.segments()[0]))
    assert shown == set(SLASH_COMMANDS)


def test_g62_declared_tools_only(env: Env) -> None:
    env.model.push(say("ok"))
    assert_clean(env.chat(["hi"]))
    names = sorted(t["function"]["name"] for t in env.model.seen[0].json["tools"])
    assert names == sorted(TOOLS)


def assert_no_runtime_dependencies(built_wheel: Path) -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    assert project.get("dependencies", []) == []
    assert "optional-dependencies" not in project
    with zipfile.ZipFile(built_wheel) as wheel:
        metadata = wheel.read(
            next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
        ).decode()
    assert [
        line for line in metadata.splitlines() if line.startswith("Requires-Dist:")
    ] == []
