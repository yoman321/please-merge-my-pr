"""Interactive setup and direct config commands."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import replace
from pathlib import Path
from typing import Any

from please_merge_my_pr.config import (
    atomic_write,
    config_from_text,
    config_path,
    default_config,
    load_config,
    to_toml,
)

FIXED_KEYS = {
    "github": {"api_url", "web_url", "token_env", "repos"},
    "model": {"base_url", "api_key_env", "name"},
    "weights": {
        "urgency",
        "blocks",
        "risk",
        "due_soon",
        "age",
        "diff",
        "ci",
    },
    "scoring": {
        "age_cap_days",
        "diff_cap_lines",
        "due_horizon_days",
        "blocked_people_cap",
    },
    "urgency_labels": {"urgent", "high", "medium", "low"},
    "files": {"lockfiles"},
    "display": {"limit"},
}


def _read(prompt: str) -> str:
    print(prompt, end="", flush=True)
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        print()
        return ""
    return line.rstrip("\n") if line else ""


def confirmed() -> bool:
    print("Write this change? [y/N] ", end="", flush=True)
    if not sys.stdin.isatty():
        print()
        return False
    try:
        answer = sys.stdin.readline()
    except KeyboardInterrupt:
        print()
        return False
    return answer.strip().casefold() in {"y", "yes"}


def run_init(path: Path | None = None) -> int:
    chosen = config_path(path)
    if chosen.exists():
        print(f"config already exists: {chosen}", file=sys.stderr)
        return 1
    repos: list[str] = []
    while True:
        repo = _read("Repository owner/name (blank when done): ").strip()
        if not repo:
            break
        repos.append(repo)
    api = _read("GitHub API URL [https://api.github.com]: ").strip()
    web = _read("GitHub web URL [https://github.com]: ").strip()
    token_env = _read("GitHub token env [GITHUB_TOKEN]: ").strip()
    use_model = _read("Configure a model? [y/n] ").strip().casefold() in {"y", "yes"}
    config = replace(
        default_config(),
        repos=tuple(repos),
        github_api_url=api or "https://api.github.com",
        github_web_url=web or "https://github.com",
        github_token_env=token_env or "GITHUB_TOKEN",
        source_path=chosen,
    )
    if use_model:
        model_base_url = _read("Model base URL: ").strip()
        model_api_key_env = _read("Model API key env (optional): ").strip()
        model_name = _read("Model name: ").strip()
        if not model_base_url:
            print("invalid config: model.base_url", file=sys.stderr)
            return 2
        if not model_name:
            print("invalid config: model.name", file=sys.stderr)
            return 2
        config = replace(
            config,
            model_base_url=model_base_url,
            model_api_key_env=model_api_key_env or None,
            model_name=model_name,
        )
    try:
        text = to_toml(config_from_text(to_toml(config), path=chosen))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"Config destination: {chosen}")
    print(text, end="")
    if not confirmed():
        return 0
    atomic_write(chosen, text)
    return 0


def run_config(command: str, values: list[str], path: Path | None = None) -> int:
    chosen = config_path(path)
    if command == "path":
        print(chosen)
        return 0
    if command == "show":
        try:
            print(to_toml(load_config(chosen)), end="")
            return 0
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if command == "set":
        if len(values) != 2:
            print("config set needs a key and TOML value", file=sys.stderr)
            return 2
        key, literal = values
        try:
            parsed = tomllib.loads(f"value = {literal}")["value"]
            current = tomllib.loads(to_toml(load_config(chosen)))
            section, dot, name = key.partition(".")
            allowed_dynamic = section == "risk_paths" and bool(name)
            allowed_fixed = name in FIXED_KEYS.get(section, set())
            if not dot or not (allowed_dynamic or allowed_fixed):
                raise ValueError(f"invalid config: {key}")
            if section not in current:
                current[section] = {}
            if not isinstance(current[section], dict):
                raise ValueError(f"invalid config: {key}")
            current[section][name] = parsed
            text = _raw_toml(current)
            validated = config_from_text(text, path=chosen)
            atomic_write(chosen, to_toml(validated))
        except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
            print(f"invalid config: {key}", file=sys.stderr)
            return 1
        return 0
    if command == "edit":
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            print("EDITOR is not set", file=sys.stderr)
            return 1
        original = to_toml(load_config(chosen))
        fd, name = tempfile.mkstemp(prefix="config-edit-", suffix=".toml")
        edit_path = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(original)
            result = subprocess.run([editor, str(edit_path)], check=False)
            if result.returncode:
                return result.returncode
            validated = config_from_text(edit_path.read_text(), path=chosen)
            atomic_write(chosen, to_toml(validated))
            return 0
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        finally:
            edit_path.unlink(missing_ok=True)
    return 2


def _raw_toml(raw: dict[str, Any]) -> str:
    """Small serializer for config-set's already canonical scalar/list tables."""
    import json

    lines: list[str] = []
    for section, values in raw.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = "true" if value else "false"
            elif isinstance(value, (int, float)):
                rendered = repr(value)
            elif isinstance(value, str):
                rendered = json.dumps(value)
            elif isinstance(value, list):
                rendered = "[" + ", ".join(json.dumps(v) for v in value) + "]"
            else:
                raise TypeError(f"invalid config: {section}.{key}")
            lines.append(f"{json.dumps(key, ensure_ascii=False)} = {rendered}")
        lines.append("")
    return "\n".join(lines)
