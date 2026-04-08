from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from geonode_spider.models.region import CrawlRunRecord, RegionNode


CREATE_REGIONS_TABLE = """
CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    level TEXT NOT NULL,
    parent_code TEXT,
    province_code TEXT,
    city_code TEXT,
    district_code TEXT,
    town_code TEXT,
    longitude REAL,
    latitude REAL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    version TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(code, version)
)
"""

CREATE_CRAWL_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    source_name TEXT NOT NULL,
    status TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    error_message TEXT NOT NULL DEFAULT ''
)
"""


class SQLiteRegionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(CREATE_REGIONS_TABLE)
            conn.execute(CREATE_CRAWL_RUNS_TABLE)
            conn.commit()

    def upsert_regions(self, regions: Iterable[RegionNode]) -> None:
        rows = [region.to_dict() for region in regions]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO regions (
                    code, name, full_name, level, parent_code, province_code,
                    city_code, district_code, town_code, longitude, latitude,
                    source_name, source_url, version, captured_at, updated_at
                ) VALUES (
                    :code, :name, :full_name, :level, :parent_code, :province_code,
                    :city_code, :district_code, :town_code, :longitude, :latitude,
                    :source_name, :source_url, :version, :captured_at, :updated_at
                )
                ON CONFLICT(code, version) DO UPDATE SET
                    name = excluded.name,
                    full_name = excluded.full_name,
                    level = excluded.level,
                    parent_code = excluded.parent_code,
                    province_code = excluded.province_code,
                    city_code = excluded.city_code,
                    district_code = excluded.district_code,
                    town_code = excluded.town_code,
                    longitude = excluded.longitude,
                    latitude = excluded.latitude,
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            conn.commit()

    def list_regions(self, *, level: str | None = None) -> list[RegionNode]:
        query = "SELECT * FROM regions"
        params: tuple[object, ...] = ()
        if level:
            query += " WHERE level = ?"
            params = (level,)
        query += " ORDER BY code"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [RegionNode.from_row(dict(row)) for row in rows]

    def record_crawl_run(self, record: CrawlRunRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_runs (
                    run_id, source_name, status, item_count, started_at, finished_at, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    item_count = excluded.item_count,
                    finished_at = excluded.finished_at,
                    error_message = excluded.error_message
                """,
                (
                    record.run_id,
                    record.source_name,
                    record.status,
                    record.item_count,
                    record.started_at,
                    record.finished_at,
                    record.error_message,
                ),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
