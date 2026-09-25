"""Minimal TOML configuration with built-in defaults."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


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


def default_config() -> Config:
    return Config(
        weights={
            "urgency": 30.0,
            "blocks": 25.0,
            "risk_paths": 15.0,
            "due_soon": 10.0,
            "age": 10.0,
            "diff_size": 5.0,
            "ci_state": 5.0,
        },
        age_cap_days=14.0,
        diff_cap_lines=500.0,
        risk_paths={
            "auth": ("auth/**",),
            "billing": ("billing/**",),
            "migrations": ("migrations/**",),
        },
        lockfiles=(
            "**/uv.lock",
            "**/package-lock.json",
            "**/yarn.lock",
            "**/pnpm-lock.yaml",
            "**/poetry.lock",
            "**/Cargo.lock",
            "**/go.sum",
        ),
        repos=(),
        github_api_url="https://api.github.com",
        github_token_env="GITHUB_TOKEN",
    )


def load_config(path: Path | None = None) -> Config:
    if path is None:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = root / "please-merge-my-pr" / "config.toml"
    if not path.exists():
        return default_config()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return _merge(default_config(), raw)


def _merge(base: Config, raw: dict[str, Any]) -> Config:
    github = raw.get("github", {})
    weights = raw.get("weights", base.weights)
    scoring = raw.get("scoring", {})
    paths = raw.get("risk_paths", base.risk_paths)
    github_api_url = str(github.get("api_url", base.github_api_url)).rstrip("/")
    if urlsplit(github_api_url).scheme.lower() != "https":
        raise ValueError("github.api_url must use https")
    return Config(
        weights={str(key): float(value) for key, value in weights.items()},
        age_cap_days=float(scoring.get("age_cap_days", base.age_cap_days)),
        diff_cap_lines=float(scoring.get("diff_cap_lines", base.diff_cap_lines)),
        risk_paths={str(key): tuple(map(str, value)) for key, value in paths.items()},
        lockfiles=tuple(map(str, raw.get("lockfiles", base.lockfiles))),
        repos=tuple(map(str, raw.get("repos", base.repos))),
        github_api_url=github_api_url,
        github_token_env=str(github.get("token_env", base.github_token_env)),
    )
