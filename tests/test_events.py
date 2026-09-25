"""Gate for I1."""

from __future__ import annotations

import dataclasses
import json

import pytest
from conftest import FIXTURES

from please_merge_my_pr.events import Event

# Known values of the fixture pair: GH Archive hour 2026-09-24-23 UTC, and
# the REST body for the same PR fetched right after (2026-09-25 02:2x UTC).
EXPECTED = Event(
    repo="Homebrew/advisory-database",
    number=609,
    base_ref="main",
    head_ref="fix/poetry-virtualenv-boundary",
)


def test_event_parity() -> None:
    archive = json.loads((FIXTURES / "gharchive_pull_request_event.json").read_text())
    rest = json.loads((FIXTURES / "github_rest_pull.json").read_text())

    assert [f.name for f in dataclasses.fields(Event)] == [
        "repo",
        "number",
        "base_ref",
        "head_ref",
    ]
    from_archive = Event.from_gh_archive(archive)
    from_rest = Event.from_github_rest(rest)

    assert from_archive == from_rest
    assert from_archive == EXPECTED
    assert from_rest.repo == "Homebrew/advisory-database"
    assert from_rest.number == 609
    assert from_rest.base_ref == "main"
    assert from_rest.head_ref == "fix/poetry-virtualenv-boundary"
    with pytest.raises(dataclasses.FrozenInstanceError):
        from_rest.number = 1  # type: ignore[misc]
