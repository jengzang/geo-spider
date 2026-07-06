from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from xzqh_spider.models import Division


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS xzqh_divisions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_code TEXT NOT NULL,
    parent_code TEXT NOT NULL,
    level TEXT NOT NULL,
    level_text TEXT NOT NULL,
    full_name TEXT NOT NULL,
    status TEXT NOT NULL,
    source_url TEXT NOT NULL,
    captured_at TEXT NOT NULL
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_xzqh_parent ON xzqh_divisions(parent_code);",
    "CREATE INDEX IF NOT EXISTS idx_xzqh_level ON xzqh_divisions(level);",
]


class XzqhRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(CREATE_TABLE)
            for idx in CREATE_INDEXES:
                conn.execute(idx)
            conn.commit()

    def upsert(self, division: Division) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO xzqh_divisions
                    (code, name, short_code, parent_code, level, level_text,
                     full_name, status, source_url, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    short_code = excluded.short_code,
                    parent_code = excluded.parent_code,
                    level = excluded.level,
                    level_text = excluded.level_text,
                    full_name = excluded.full_name,
                    status = excluded.status,
                    source_url = excluded.source_url,
                    captured_at = excluded.captured_at
                """,
                (
                    division.code, division.name, division.short_code,
                    division.parent_code, division.level, division.level_text,
                    division.full_name, division.status, division.source_url,
                    division.captured_at,
                ),
            )
            conn.commit()

    def upsert_many(self, divisions: Iterable[Division]) -> None:
        rows = [
            (
                d.code, d.name, d.short_code, d.parent_code, d.level,
                d.level_text, d.full_name, d.status, d.source_url, d.captured_at,
            )
            for d in divisions
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO xzqh_divisions
                    (code, name, short_code, parent_code, level, level_text,
                     full_name, status, source_url, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    short_code = excluded.short_code,
                    parent_code = excluded.parent_code,
                    level = excluded.level,
                    level_text = excluded.level_text,
                    full_name = excluded.full_name,
                    status = excluded.status,
                    source_url = excluded.source_url,
                    captured_at = excluded.captured_at
                """,
                rows,
            )
            conn.commit()

    def exists(self, code: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM xzqh_divisions WHERE code = ?", (code,)).fetchone()
        return row is not None

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM xzqh_divisions").fetchone()
        return int(row[0])

    def count_by_level(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT level, COUNT(*) as cnt FROM xzqh_divisions GROUP BY level"
            ).fetchall()
        return {row["level"]: row["cnt"] for row in rows}

    def list_all(self) -> list[Division]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM xzqh_divisions ORDER BY code"
            ).fetchall()
        return [_row_to_division(dict(row)) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


def _row_to_division(row: dict[str, object]) -> Division:
    return Division(
        code=str(row["code"]),
        name=str(row["name"]),
        short_code=str(row["short_code"]),
        parent_code=str(row["parent_code"]),
        level=str(row["level"]),
        level_text=str(row["level_text"]),
        full_name=str(row["full_name"]),
        status=str(row["status"]),
        source_url=str(row["source_url"]),
        captured_at=str(row["captured_at"]),
    )
