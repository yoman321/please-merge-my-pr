"""Gates for phase 1, I12, I13."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import (
    ALL_COMMANDS,
    REPO_ROOT,
    STUBS,
    all_files,
    assert_ran,
    guard,
    run_cli,
)

SRC = REPO_ROOT / "src" / "please_merge_my_pr"

MODEL_CLIENTS = (
    "openai",
    "anthropic",
    "langsmith",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "litellm",
    "mistralai",
    "cohere",
    "ollama",
    "groq",
    "together",
    "replicate",
    "google.generativeai",
    "google.genai",
    "vertexai",
    "transformers",
    "huggingface_hub",
)


def help_commands(text: str) -> set[str]:
    """The subcommand choices argparse lists as `{a,b,c}` in help output."""
    match = re.search(r"\{([a-z][a-z0-9_-]*(?:,[a-z][a-z0-9_-]*)+)\}", text)
    assert match, f"no {{command,...}} choice list in help:\n{text}"
    return set(match.group(1).split(","))


def test_package_and_command_tree(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        names = wheel.namelist()
        metadata = wheel.read(
            next(n for n in names if n.endswith(".dist-info/METADATA"))
        ).decode()
        entry_points = wheel.read(
            next(n for n in names if n.endswith(".dist-info/entry_points.txt"))
        ).decode()
    requires = [
        line for line in metadata.splitlines() if line.startswith("Requires-Dist:")
    ]
    assert requires == [], f"runtime dependencies: {requires}"
    assert re.search(r"^Requires-Python: >=3\.13$", metadata, re.MULTILINE), metadata
    assert re.search(
        r"^please-merge-my-pr = please_merge_my_pr\.cli:main$",
        entry_points,
        re.MULTILINE,
    ), entry_points

    script = Path(sys.executable).parent / "please-merge-my-pr"
    assert script.exists(), f"console script not installed at {script}"
    via_script = subprocess.run(
        [str(script), "--help"], capture_output=True, text=True, timeout=60, check=False
    )
    via_module = subprocess.run(
        [sys.executable, "-m", "please_merge_my_pr", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    for proc in (via_script, via_module):
        assert proc.returncode == 0, proc.stderr
        assert help_commands(proc.stdout) == ALL_COMMANDS
    assert "--demo" in via_script.stdout
    assert "--config" in via_script.stdout


@pytest.mark.parametrize("command", sorted(ALL_COMMANDS))
def test_package_and_command_tree_help(
    command: str, isolated: Mapping[str, Path]
) -> None:
    with guard(network=True, writes=True, subprocess=True):
        result = run_cli([command, "--help"])
    assert_ran(result, 0)
    assert result.err == ""
    lines = [line for line in result.out.splitlines() if line.strip()]
    assert any(command in line for line in lines), result.out
    purpose = [
        line
        for line in lines
        if not line.lower().startswith("usage:")
        and not line.startswith(" ")
        and not line.endswith(":")
    ]
    assert purpose, f"no one-line purpose in help for {command}:\n{result.out}"


@pytest.mark.parametrize(
    ("command", "args"),
    [(c, []) for c in sorted(STUBS)]
    + [(c, ["--anything", "x", "-y", "42", "owner/repo#1"]) for c in sorted(STUBS)],
)
def test_stubs_inert(
    command: str, args: list[str], isolated: Mapping[str, Path]
) -> None:
    root = isolated["home"].parent
    before = all_files(root)
    with guard(network=True, writes=True, subprocess=True) as violations:
        result = run_cli([command, *args])
    assert violations == []
    assert_ran(result, 2)
    assert result.err == f"not built yet — see plans/{STUBS[command]}.md\n"
    assert result.out == ""
    assert all_files(root) == before


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
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


def is_model_client(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in MODEL_CLIENTS)


def test_no_llm_imports(
    isolated: Mapping[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Static half: no module under src/please_merge_my_pr/ imports a model client.
    sources = sorted(SRC.rglob("*.py"))
    assert sources
    offenders = {
        str(p.relative_to(SRC)): sorted(filter(is_model_client, imported_modules(p)))
        for p in sources
    }
    assert {k: v for k, v in offenders.items() if v} == {}

    # Runtime half (approved by the human 2026-09-24): run every built command
    # in demo mode and check that no model client module was loaded.
    for name in list(sys.modules):
        if is_model_client(name):
            monkeypatch.delitem(sys.modules, name)
    listing = run_cli(["list", "--demo", "--all", "--json"])
    assert_ran(listing)
    first = json.loads(listing.out)["items"][0]
    target = f"{first['repo']}#{first['number']}"
    for argv in (
        ["list", "--demo"],
        ["why", target, "--demo"],
        ["show", target, "--demo"],
        ["watch", "--demo"],
    ):
        assert_ran(run_cli(argv))
    assert sorted(name for name in sys.modules if is_model_client(name)) == []
