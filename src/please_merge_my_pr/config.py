"""Validated TOML configuration and atomic persistence."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

WEIGHT_KEYS = ("urgency", "blocks", "risk", "due_soon", "age", "diff", "ci")
WEIGHT_ALIASES = {"risk_paths": "risk", "diff_size": "diff", "ci_state": "ci"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
REPO_NAME = re.compile(r"^[^/\s]+/[^/\s]+$")


@dataclass(frozen=True)
class Config:
    weights: Mapping[str, float]
    age_cap_days: float
    diff_cap_lines: float
    risk_paths: Mapping[str, tuple[str, ...]]
    lockfiles: tuple[str, ...]
    repos: tuple[str, ...]
    github_api_url: str
    github_token_env: str
    github_web_url: str = "https://github.com"
    model_base_url: str | None = None
    model_api_key_env: str | None = None
    model_name: str | None = None
    due_horizon_days: float = 14.0
    blocked_people_cap: float = 3.0
    urgency_labels: Mapping[str, float] | None = None
    display_limit: int = 3
    source_path: Path | None = None


def config_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "please-merge-my-pr" / "config.toml"


def default_config() -> Config:
    return Config(
        weights={
            "urgency": 30.0,
            "blocks": 25.0,
            "risk": 15.0,
            "due_soon": 10.0,
            "age": 10.0,
            "diff": 5.0,
            "ci": 5.0,
        },
        age_cap_days=14.0,
        diff_cap_lines=500.0,
        risk_paths={
            "auth": ("auth/**",),
            "billing": ("billing/**",),
            "migrations": ("migrations/**",),
        },
        lockfiles=("**/uv.lock", "**/package-lock.json"),
        repos=(),
        github_api_url="https://api.github.com",
        github_token_env="GITHUB_TOKEN",
        github_web_url="https://github.com",
        urgency_labels={"urgent": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25},
    )


def load_config(path: Path | None = None) -> Config:
    chosen = config_path(path)
    if not chosen.exists():
        return replace(default_config(), source_path=chosen)
    try:
        with chosen.open("rb") as handle:
            raw = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {exc}") from None
    return replace(_merge(default_config(), raw), source_path=chosen)


def config_from_text(text: str, *, path: Path | None = None) -> Config:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {exc}") from None
    return replace(_merge(default_config(), raw), source_path=path)


def _error(key: str) -> ValueError:
    return ValueError(f"invalid config: {key}")


def _table(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise _error(name)
    return value


def _known(table: Mapping[str, Any], allowed: set[str], prefix: str) -> None:
    extra = set(table) - allowed
    if extra:
        raise _error(f"{prefix}.{min(extra)}")


def _finite(
    value: Any, key: str, *, low: float | None = None, high: float | None = None
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _error(key)
    out = float(value)
    if (
        not math.isfinite(out)
        or (low is not None and out < low)
        or (high is not None and out > high)
    ):
        raise _error(key)
    return out


def _base_url(value: Any, key: str, *, model: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise _error(key)
    parsed = urlsplit(value)
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise _error(key)
    if not parsed.hostname:
        raise _error(key)
    if parsed.scheme == "https":
        return value.rstrip("/")
    if model and parsed.scheme == "http":
        host = parsed.hostname
        if host == "::1":
            return value.rstrip("/")
        parts = host.split(".") if host else []
        if len(parts) == 4 and all(p.isdigit() and str(int(p)) == p for p in parts):
            nums = [int(p) for p in parts]
            if nums[0] == 127 and all(0 <= p <= 255 for p in nums):
                return value.rstrip("/")
    raise _error(key)


def _env(value: Any, key: str) -> str:
    if not isinstance(value, str) or not ENV_NAME.fullmatch(value):
        raise _error(key)
    return value


def _strings(
    value: Any, key: str, *, repos: bool = False, globs: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise _error(key)
    out = tuple(value)
    if len(set(out)) != len(out) or any(not item for item in out):
        raise _error(key)
    if repos and any(not REPO_NAME.fullmatch(item) for item in out):
        raise _error(key)
    if globs and any(PurePosixPath(item).is_absolute() for item in out):
        raise _error(key)
    return out


def _merge(base: Config, raw: dict[str, Any]) -> Config:
    allowed = {
        "github",
        "model",
        "weights",
        "scoring",
        "urgency_labels",
        "risk_paths",
        "files",
        "display",
        "repos",
        "lockfiles",
    }
    extra = set(raw) - allowed
    if extra:
        raise _error(min(extra))
    github, model = _table(raw, "github"), _table(raw, "model")
    scoring, display, files = (
        _table(raw, "scoring"),
        _table(raw, "display"),
        _table(raw, "files"),
    )
    paths, urgency, weights_raw = (
        _table(raw, "risk_paths"),
        _table(raw, "urgency_labels"),
        _table(raw, "weights"),
    )
    _known(github, {"api_url", "web_url", "token_env", "repos"}, "github")
    _known(model, {"base_url", "api_key_env", "name"}, "model")
    _known(
        scoring,
        {"age_cap_days", "diff_cap_lines", "due_horizon_days", "blocked_people_cap"},
        "scoring",
    )
    _known(display, {"limit"}, "display")
    _known(files, {"lockfiles"}, "files")

    weights: dict[str, float] = {}
    for raw_name, raw_value in weights_raw.items():
        name = WEIGHT_ALIASES.get(raw_name, raw_name)
        if name not in WEIGHT_KEYS or name in weights:
            raise _error(f"weights.{name}")
        weights[name] = _finite(raw_value, f"weights.{name}", low=0.0, high=100.0)
    if not weights_raw:
        weights = dict(base.weights)
    elif set(weights) != set(WEIGHT_KEYS):
        missing = next((name for name in WEIGHT_KEYS if name not in weights), "weights")
        raise _error(f"weights.{missing}")
    if not any(weights.values()):
        raise _error("weights")

    if "repos" in raw and "repos" in github:
        raise _error("repos")
    repos = _strings(
        github.get("repos", raw.get("repos", list(base.repos))),
        "github.repos",
        repos=True,
    )
    if "lockfiles" in raw and "lockfiles" in files:
        raise _error("lockfiles")
    lockfiles = _strings(
        files.get("lockfiles", raw.get("lockfiles", list(base.lockfiles))),
        "files.lockfiles",
        globs=True,
    )

    risk_paths: dict[str, tuple[str, ...]] = {}
    for name, patterns in (paths or base.risk_paths).items():
        if not isinstance(name, str) or not name:
            raise _error("risk_paths")
        risk_paths[name] = _strings(patterns, f"risk_paths.{name}", globs=True)
    urgency_labels: dict[str, float] = {}
    for name, value in (urgency or base.urgency_labels or {}).items():
        if not isinstance(name, str) or not name:
            raise _error("urgency_labels")
        urgency_labels[name] = _finite(
            value, f"urgency_labels.{name}", low=0.0, high=1.0
        )

    api_url = _base_url(github.get("api_url", base.github_api_url), "github.api_url")
    web_url = _base_url(github.get("web_url", base.github_web_url), "github.web_url")
    token_env = _env(github.get("token_env", base.github_token_env), "github.token_env")
    model_base: str | None = None
    model_key: str | None = None
    model_name: str | None = None
    if "model" in raw:
        if "base_url" in model:
            model_base = _base_url(model["base_url"], "model.base_url", model=True)
        if "api_key_env" in model:
            model_key = _env(model["api_key_env"], "model.api_key_env")
        if "name" in model:
            model_name_value = model["name"]
            if not isinstance(model_name_value, str) or not model_name_value:
                raise _error("model.name")
            model_name = model_name_value

    age = _finite(
        scoring.get("age_cap_days", base.age_cap_days), "scoring.age_cap_days", low=0.0
    )
    diff = _finite(
        scoring.get("diff_cap_lines", base.diff_cap_lines),
        "scoring.diff_cap_lines",
        low=0.0,
    )
    due = _finite(
        scoring.get("due_horizon_days", base.due_horizon_days),
        "scoring.due_horizon_days",
        low=0.0,
    )
    blocked = _finite(
        scoring.get("blocked_people_cap", base.blocked_people_cap),
        "scoring.blocked_people_cap",
        low=0.0,
    )
    for key, value in (
        ("age_cap_days", age),
        ("diff_cap_lines", diff),
        ("due_horizon_days", due),
        ("blocked_people_cap", blocked),
    ):
        if value <= 0:
            raise _error(f"scoring.{key}")
    limit = display.get("limit", base.display_limit)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise _error("display.limit")
    return Config(
        weights,
        age,
        diff,
        risk_paths,
        lockfiles,
        repos,
        api_url,
        token_env,
        web_url,
        model_base,
        model_key,
        model_name,
        due,
        blocked,
        urgency_labels,
        limit,
    )


def to_toml(config: Config) -> str:
    q = lambda value: json.dumps(value, ensure_ascii=False)
    arr = lambda values: "[" + ", ".join(q(v) for v in values) + "]"
    lines = [
        "[github]",
        f"api_url = {q(config.github_api_url)}",
        f"web_url = {q(config.github_web_url)}",
        f"token_env = {q(config.github_token_env)}",
        f"repos = {arr(config.repos)}",
        "",
    ]
    if any(
        value is not None
        for value in (
            config.model_base_url,
            config.model_api_key_env,
            config.model_name,
        )
    ):
        lines.append("[model]")
        if config.model_base_url is not None:
            lines.append(f"base_url = {q(config.model_base_url)}")
        if config.model_api_key_env is not None:
            lines.append(f"api_key_env = {q(config.model_api_key_env)}")
        if config.model_name is not None:
            lines.append(f"name = {q(config.model_name)}")
        lines.append("")
    lines.append("[weights]")
    lines.extend(f"{name} = {float(config.weights[name])!r}" for name in WEIGHT_KEYS)
    lines += [
        "",
        "[scoring]",
        f"age_cap_days = {config.age_cap_days!r}",
        f"diff_cap_lines = {config.diff_cap_lines!r}",
        f"due_horizon_days = {config.due_horizon_days!r}",
        f"blocked_people_cap = {config.blocked_people_cap!r}",
        "",
        "[urgency_labels]",
    ]
    lines.extend(
        f"{q(name)} = {float(value)!r}"
        for name, value in (config.urgency_labels or {}).items()
    )
    lines += ["", "[risk_paths]"]
    lines.extend(
        f"{q(name)} = {arr(tuple(patterns))}"
        for name, patterns in config.risk_paths.items()
    )
    lines += [
        "",
        "[files]",
        f"lockfiles = {arr(config.lockfiles)}",
        "",
        "[display]",
        f"limit = {config.display_limit}",
        "",
    ]
    return "\n".join(lines)


def atomic_write(path: Path, text: str, *, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_bytes() if path.exists() else None
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode())
            handle.flush()
            os.fsync(handle.fileno())
        if backup and old is not None:
            path.with_name(path.name + ".bak").write_bytes(old)
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()


def with_weights(config: Config, weights: Mapping[str, float]) -> Config:
    return replace(config, weights={name: float(weights[name]) for name in WEIGHT_KEYS})
