"""SQLite metadata used by notification polling."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS poll_state (
                    key TEXT PRIMARY KEY,
                    last_modified TEXT,
                    etag TEXT,
                    poll_interval INTEGER NOT NULL,
                    last_poll_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS seen (
                    repo TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    requested_at TEXT NOT NULL,
                    PRIMARY KEY (repo, number, requested_at)
                );
                CREATE TABLE IF NOT EXISTS action_rules (
                    rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    adds TEXT NOT NULL,
                    removes TEXT NOT NULL,
                    UNIQUE(repo, adds, removes)
                );
                CREATE TABLE IF NOT EXISTS hidden (
                    repo TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    PRIMARY KEY(repo, number)
                );
                CREATE TABLE IF NOT EXISTS snoozes (
                    repo TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    until_at TEXT NOT NULL,
                    PRIMARY KEY(repo, number)
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    call_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_bytes INTEGER NOT NULL,
                    response_bytes INTEGER NOT NULL,
                    latency_ms REAL NOT NULL,
                    outcome_class TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER
                );
                CREATE TABLE IF NOT EXISTS model_turns (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_count INTEGER NOT NULL,
                    request_bytes INTEGER NOT NULL,
                    response_bytes INTEGER NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    token_usage_complete INTEGER NOT NULL
                );
                """
            )

    def poll_state(self, key: str) -> tuple[str | None, str | None, int, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_modified, etag, poll_interval, last_poll_at "
                "FROM poll_state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return row[0], row[1], int(row[2]), str(row[3])

    def save_poll_state(
        self,
        key: str,
        last_modified: str | None,
        etag: str | None,
        poll_interval: int,
        last_poll_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO poll_state(key, last_modified, etag, poll_interval, last_poll_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    last_modified = excluded.last_modified,
                    etag = excluded.etag,
                    poll_interval = excluded.poll_interval,
                    last_poll_at = excluded.last_poll_at
                """,
                (key, last_modified, etag, poll_interval, last_poll_at),
            )

    def has_seen(self, repo: str, number: int, requested_at: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM seen WHERE repo = ? AND number = ? AND requested_at = ?",
                (repo, number, requested_at),
            ).fetchone()
        return row is not None

    def mark_seen(self, repo: str, number: int, requested_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO seen(repo, number, requested_at) VALUES (?, ?, ?)",
                (repo, number, requested_at),
            )

    def add_rule(
        self, repo: str, adds: tuple[str, ...], removes: tuple[str, ...]
    ) -> int:
        import json

        add_text = json.dumps(sorted(adds), separators=(",", ":"))
        remove_text = json.dumps(sorted(removes), separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO action_rules(repo, adds, removes) VALUES (?, ?, ?)",
                (repo, add_text, remove_text),
            )
            row = connection.execute(
                "SELECT rule_id FROM action_rules WHERE repo=? AND adds=? AND removes=?",
                (repo, add_text, remove_text),
            ).fetchone()
        assert row is not None
        return int(row[0])

    def rules(self) -> list[tuple[int, str, str, str]]:
        with self._connect() as connection:
            return [
                (int(a), str(b), str(c), str(d))
                for a, b, c, d in connection.execute(
                    "SELECT rule_id, repo, adds, removes FROM action_rules ORDER BY rule_id"
                )
            ]

    def remove_rule(self, rule_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM action_rules WHERE rule_id=?", (rule_id,)
            )
        return cursor.rowcount == 1

    def rule_matches(
        self, repo: str, adds: tuple[str, ...], removes: tuple[str, ...]
    ) -> bool:
        import json

        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM action_rules WHERE repo=? AND adds=? AND removes=?",
                (
                    repo,
                    json.dumps(sorted(adds), separators=(",", ":")),
                    json.dumps(sorted(removes), separators=(",", ":")),
                ),
            ).fetchone()
        return row is not None

    def hide(self, repo: str, number: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO hidden(repo, number) VALUES (?, ?)",
                (repo, number),
            )

    def unhide(self, repo: str, number: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM hidden WHERE repo=? AND number=?", (repo, number)
            )

    def snooze(self, repo: str, number: int, until_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO snoozes(repo, number, until_at) VALUES (?, ?, ?) ON CONFLICT(repo, number) DO UPDATE SET until_at=excluded.until_at",
                (repo, number, until_at),
            )

    def filtered(self, repo: str, number: int, now_iso: str) -> bool:
        with self._connect() as connection:
            hidden = connection.execute(
                "SELECT 1 FROM hidden WHERE repo=? AND number=?", (repo, number)
            ).fetchone()
            snoozed = connection.execute(
                "SELECT 1 FROM snoozes WHERE repo=? AND number=? AND until_at>?",
                (repo, number, now_iso),
            ).fetchone()
            connection.execute("DELETE FROM snoozes WHERE until_at<=?", (now_iso,))
        return hidden is not None or snoozed is not None

    def record_call(
        self,
        request_bytes: int,
        response_bytes: int,
        latency_ms: float,
        outcome: str,
        model: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_calls(request_bytes,response_bytes,latency_ms,outcome_class,model_name,input_tokens,output_tokens) VALUES (?,?,?,?,?,?,?)",
                (
                    request_bytes,
                    response_bytes,
                    latency_ms,
                    outcome,
                    model,
                    input_tokens,
                    output_tokens,
                ),
            )

    def record_turn(
        self,
        request_count: int,
        request_bytes: int,
        response_bytes: int,
        input_tokens: int | None,
        output_tokens: int | None,
        complete: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_turns(request_count,request_bytes,response_bytes,input_tokens,output_tokens,token_usage_complete) VALUES (?,?,?,?,?,?)",
                (
                    request_count,
                    request_bytes,
                    response_bytes,
                    input_tokens,
                    output_tokens,
                    int(complete),
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)
