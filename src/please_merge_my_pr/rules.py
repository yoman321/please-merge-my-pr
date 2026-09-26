"""Exact tier-two label rules."""

from __future__ import annotations

import json

from please_merge_my_pr.store import Store


def add(store: Store, repo: str, adds: list[str], removes: list[str]) -> int:
    return store.add_rule(repo, tuple(sorted(adds)), tuple(sorted(removes)))


def listing(store: Store) -> str:
    rows = []
    for rule_id, repo, adds, removes in store.rules():
        rows.append(
            f"{rule_id} {repo} add={json.loads(adds)} remove={json.loads(removes)}"
        )
    return "\n".join(rows) + ("\n" if rows else "")
