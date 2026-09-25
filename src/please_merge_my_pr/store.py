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

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)
