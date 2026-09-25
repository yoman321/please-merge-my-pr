"""GitHub token lookup without exposing token text."""

from __future__ import annotations

import os
import subprocess

from please_merge_my_pr.config import Config


class AuthError(Exception):
    pass


def token(config: Config) -> str:
    from_env = os.environ.get(config.github_token_env, "").strip()
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise AuthError("GitHub token not found") from None
    found = result.stdout.strip() if result.returncode == 0 else ""
    if not found:
        raise AuthError("GitHub token not found")
    return found
