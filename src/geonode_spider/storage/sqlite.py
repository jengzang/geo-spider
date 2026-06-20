from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar

from geonode_spider.models.place import DmfwDivision, DmfwPlaceRecord
from geonode_spider.models.region import CrawlRunRecord, RegionNode


SQLITE_TIMEOUT_SECONDS = 30.0
SQLITE_BUSY_TIMEOUT_MS = 30000
SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.25
T = TypeVar("T")


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

CREATE_DMFW_DIVISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS dmfw_divisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_code TEXT NOT NULL,
    level TEXT NOT NULL,
    source_name TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

CREATE_DMFW_PLACES_TABLE = """
CREATE TABLE IF NOT EXISTS dmfw_places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    place_code TEXT NOT NULL,
    standard_name TEXT NOT NULL,
    place_type TEXT NOT NULL,
    place_type_code TEXT NOT NULL,
    province_name TEXT NOT NULL,
    city_name TEXT,
    area_name TEXT,
    area_code TEXT,
    longitude REAL,
    latitude REAL,
    keyword TEXT NOT NULL,
    partition_code TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_name TEXT NOT NULL,
    roman_alphabet_spelling TEXT NOT NULL DEFAULT '',
    ethnic_minorities_writing TEXT NOT NULL DEFAULT '',
    raw_payload_json TEXT NOT NULL DEFAULT '',
    geometry_type TEXT NOT NULL DEFAULT '',
    coordinates_json TEXT NOT NULL DEFAULT '',
    match_mode TEXT NOT NULL DEFAULT 'contain',
    fetched_at_utc TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

CREATE_DMFW_TOTAL_SINGLE_PLACES_TABLE = """
CREATE TABLE IF NOT EXISTS dmfw_places_single (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    place_code TEXT NOT NULL,
    standard_name TEXT NOT NULL,
    place_type TEXT NOT NULL,
    place_type_code TEXT NOT NULL,
    province_name TEXT NOT NULL,
    city_name TEXT,
    area_name TEXT,
    area_code TEXT,
    longitude REAL,
    latitude REAL,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

CREATE_DMFW_TOTAL_MULTI_PLACES_TABLE = """
CREATE TABLE IF NOT EXISTS dmfw_places_multi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    place_code TEXT NOT NULL,
    standard_name TEXT NOT NULL,
    place_type TEXT NOT NULL,
    place_type_code TEXT NOT NULL,
    province_name TEXT NOT NULL,
    city_name TEXT,
    area_name TEXT,
    area_code TEXT,
    geometry_type TEXT NOT NULL,
    coordinates_json TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    return conn


def _is_locked_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def _run_with_locked_retry(
    operation: Callable[[], T],
    *,
    attempts: int = SQLITE_LOCK_RETRY_ATTEMPTS,
    delay_seconds: float = SQLITE_LOCK_RETRY_DELAY_SECONDS,
) -> T:
    last_error: sqlite3.OperationalError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if not _is_locked_error(exc) or attempt >= attempts:
                raise
            last_error = exc
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable retry state")


class SQLiteDivisionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(CREATE_CRAWL_RUNS_TABLE)
                conn.execute(CREATE_DMFW_DIVISIONS_TABLE)
                conn.execute(CREATE_DMFW_PLACES_TABLE)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_dmfw_divisions_parent_code ON dmfw_divisions(parent_code)")
                _ensure_dmfw_place_columns(conn)
                conn.commit()

        _run_with_locked_retry(_write)

    def upsert_divisions(self, divisions: Iterable[DmfwDivision]) -> None:
        rows = [division.to_dict() for division in divisions]
        if not rows:
            return
        def _write() -> None:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO dmfw_divisions (
                        code, name, parent_code, level, source_name, captured_at, updated_at
                    ) VALUES (
                        :code, :name, :parent_code, :level, :source_name, :captured_at, :updated_at
                    )
                    ON CONFLICT(code) DO UPDATE SET
                        name = excluded.name,
                        parent_code = excluded.parent_code,
                        level = excluded.level,
                        source_name = excluded.source_name,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
                conn.commit()

        _run_with_locked_retry(_write)

    def list_divisions(self, *, parent_code: str = "0") -> list[DmfwDivision]:
        query = "SELECT code, name, parent_code, level, source_name, captured_at, updated_at FROM dmfw_divisions WHERE parent_code = ? ORDER BY code"
        with self._connect() as conn:
            rows = conn.execute(query, (parent_code,)).fetchall()
        return [DmfwDivision(**dict(row)) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT_SECONDS)
        return _configure_connection(conn)


class SQLiteRegionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(CREATE_REGIONS_TABLE)
                conn.execute(CREATE_CRAWL_RUNS_TABLE)
                conn.execute(CREATE_DMFW_PLACES_TABLE)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_regions_level ON regions(level)")
                _ensure_dmfw_place_columns(conn)
                conn.commit()

        _run_with_locked_retry(_write)

    def upsert_regions(self, regions: Iterable[RegionNode]) -> None:
        rows = [region.to_dict() for region in regions]
        if not rows:
            return
        def _write() -> None:
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

        _run_with_locked_retry(_write)

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
        def _write() -> None:
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

        _run_with_locked_retry(_write)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT_SECONDS)
        return _configure_connection(conn)


class SQLitePlaceRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(CREATE_DMFW_PLACES_TABLE)
                conn.execute(CREATE_CRAWL_RUNS_TABLE)
                _ensure_dmfw_place_columns(conn)
                conn.commit()

        _run_with_locked_retry(_write)

    def upsert_places(self, places: Iterable[DmfwPlaceRecord]) -> None:
        rows = [place.to_dict() for place in places]
        if not rows:
            return
        def _write() -> None:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO dmfw_places (
                        source_id, place_code, standard_name, place_type, place_type_code,
                        province_name, city_name, area_name, area_code, longitude, latitude,
                        keyword, partition_code, source_url, source_name,
                        roman_alphabet_spelling, ethnic_minorities_writing, raw_payload_json,
                        geometry_type, coordinates_json, match_mode, fetched_at_utc, captured_at, updated_at
                    ) VALUES (
                        :source_id, :place_code, :standard_name, :place_type, :place_type_code,
                        :province_name, :city_name, :area_name, :area_code, :longitude, :latitude,
                        :keyword, :partition_code, :source_url, :source_name,
                        :roman_alphabet_spelling, :ethnic_minorities_writing, :raw_payload_json,
                        :geometry_type, :coordinates_json, :match_mode, :fetched_at_utc, :captured_at, :updated_at
                    )
                    ON CONFLICT(source_id) DO UPDATE SET
                        place_code = excluded.place_code,
                        standard_name = excluded.standard_name,
                        place_type = excluded.place_type,
                        place_type_code = excluded.place_type_code,
                        province_name = excluded.province_name,
                        city_name = excluded.city_name,
                        area_name = excluded.area_name,
                        area_code = excluded.area_code,
                        longitude = excluded.longitude,
                        latitude = excluded.latitude,
                        keyword = excluded.keyword,
                        partition_code = excluded.partition_code,
                        source_url = excluded.source_url,
                        source_name = excluded.source_name,
                        roman_alphabet_spelling = excluded.roman_alphabet_spelling,
                        ethnic_minorities_writing = excluded.ethnic_minorities_writing,
                        raw_payload_json = excluded.raw_payload_json,
                        geometry_type = excluded.geometry_type,
                        coordinates_json = excluded.coordinates_json,
                        match_mode = excluded.match_mode,
                        fetched_at_utc = excluded.fetched_at_utc,
                        updated_at = excluded.updated_at
                    """,
                    rows,
                )
                conn.commit()

        _run_with_locked_retry(_write)

    def list_places(self) -> list[DmfwPlaceRecord]:
        query = """
        SELECT * FROM dmfw_places
        ORDER BY province_name, city_name, area_name, standard_name, source_id
        """
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [DmfwPlaceRecord.from_row(dict(row)) for row in rows]

    def count_places(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM dmfw_places").fetchone()
        return int(row[0])

    def record_crawl_run(self, record: CrawlRunRecord) -> None:
        def _write() -> None:
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

        _run_with_locked_retry(_write)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT_SECONDS)
        return _configure_connection(conn)


class SQLiteTotalPlaceRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        def _write() -> None:
            with self._connect() as conn:
                conn.execute(CREATE_DMFW_TOTAL_SINGLE_PLACES_TABLE)
                conn.execute(CREATE_DMFW_TOTAL_MULTI_PLACES_TABLE)
                conn.execute(CREATE_CRAWL_RUNS_TABLE)
                conn.commit()

        _run_with_locked_retry(_write)

    def upsert_places(self, places: Iterable[DmfwPlaceRecord]) -> None:
        single_rows = [place.to_total_single_dict() for place in places if place.has_single_coordinate()]
        multi_rows = [place.to_total_multi_dict() for place in places if place.has_multi_coordinates()]
        def _write() -> None:
            with self._connect() as conn:
                if single_rows:
                    conn.executemany(
                        """
                        INSERT INTO dmfw_places_single (
                            source_id, place_code, standard_name, place_type, place_type_code,
                            province_name, city_name, area_name, area_code, longitude, latitude,
                            captured_at, updated_at
                        ) VALUES (
                            :source_id, :place_code, :standard_name, :place_type, :place_type_code,
                            :province_name, :city_name, :area_name, :area_code, :longitude, :latitude,
                            :captured_at, :updated_at
                        )
                        ON CONFLICT(source_id) DO UPDATE SET
                            place_code = excluded.place_code,
                            standard_name = excluded.standard_name,
                            place_type = excluded.place_type,
                            place_type_code = excluded.place_type_code,
                            province_name = excluded.province_name,
                            city_name = excluded.city_name,
                            area_name = excluded.area_name,
                            area_code = excluded.area_code,
                            longitude = excluded.longitude,
                            latitude = excluded.latitude,
                            updated_at = excluded.updated_at
                        """,
                        single_rows,
                    )
                if multi_rows:
                    conn.executemany(
                        """
                        INSERT INTO dmfw_places_multi (
                            source_id, place_code, standard_name, place_type, place_type_code,
                            province_name, city_name, area_name, area_code, geometry_type, coordinates_json,
                            captured_at, updated_at
                        ) VALUES (
                            :source_id, :place_code, :standard_name, :place_type, :place_type_code,
                            :province_name, :city_name, :area_name, :area_code, :geometry_type, :coordinates_json,
                            :captured_at, :updated_at
                        )
                        ON CONFLICT(source_id) DO UPDATE SET
                            place_code = excluded.place_code,
                            standard_name = excluded.standard_name,
                            place_type = excluded.place_type,
                            place_type_code = excluded.place_type_code,
                            province_name = excluded.province_name,
                            city_name = excluded.city_name,
                            area_name = excluded.area_name,
                            area_code = excluded.area_code,
                            geometry_type = excluded.geometry_type,
                            coordinates_json = excluded.coordinates_json,
                            updated_at = excluded.updated_at
                        """,
                        multi_rows,
                    )
                conn.commit()

        _run_with_locked_retry(_write)

    def list_places(self) -> list[DmfwPlaceRecord]:
        with self._connect() as conn:
            single_rows = conn.execute(
                """
                SELECT *, 'single' AS geometry_bucket
                FROM dmfw_places_single
                ORDER BY province_name, city_name, area_name, standard_name, source_id
                """
            ).fetchall()
            multi_rows = conn.execute(
                """
                SELECT *, 'multi' AS geometry_bucket
                FROM dmfw_places_multi
                ORDER BY province_name, city_name, area_name, standard_name, source_id
                """
            ).fetchall()
        records = [_single_total_row_to_record(dict(row)) for row in single_rows]
        records.extend(_multi_total_row_to_record(dict(row)) for row in multi_rows)
        records.sort(key=lambda row: (row.province_name, row.city_name or "", row.area_name or "", row.standard_name, row.source_id))
        return records

    def count_places(self) -> int:
        with self._connect() as conn:
            single_count = conn.execute("SELECT COUNT(*) FROM dmfw_places_single").fetchone()[0]
            multi_count = conn.execute("SELECT COUNT(*) FROM dmfw_places_multi").fetchone()[0]
        return int(single_count) + int(multi_count)

    def count_single_places(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM dmfw_places_single").fetchone()
        return int(row[0])

    def count_multi_places(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM dmfw_places_multi").fetchone()
        return int(row[0])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=SQLITE_TIMEOUT_SECONDS)
        return _configure_connection(conn)


def _single_total_row_to_record(row: dict[str, object]) -> DmfwPlaceRecord:
    return DmfwPlaceRecord(
        source_id=str(row["source_id"]),
        place_code=str(row["place_code"]),
        standard_name=str(row["standard_name"]),
        place_type=str(row["place_type"]),
        place_type_code=str(row["place_type_code"]),
        province_name=str(row["province_name"]),
        city_name=row["city_name"] if row["city_name"] not in (None, "") else None,
        area_name=row["area_name"] if row["area_name"] not in (None, "") else None,
        area_code=row["area_code"] if row["area_code"] not in (None, "") else None,
        longitude=row["longitude"] if row["longitude"] is None else float(row["longitude"]),
        latitude=row["latitude"] if row["latitude"] is None else float(row["latitude"]),
        keyword="",
        partition_code="",
        source_url="",
        source_name="dmfw",
        roman_alphabet_spelling="",
        ethnic_minorities_writing="",
        raw_payload_json="",
        match_mode="",
        fetched_at_utc="",
        captured_at=str(row["captured_at"]),
        updated_at=str(row["updated_at"]),
        geometry_type="point",
        coordinates_json="",
    )


def _multi_total_row_to_record(row: dict[str, object]) -> DmfwPlaceRecord:
    return DmfwPlaceRecord(
        source_id=str(row["source_id"]),
        place_code=str(row["place_code"]),
        standard_name=str(row["standard_name"]),
        place_type=str(row["place_type"]),
        place_type_code=str(row["place_type_code"]),
        province_name=str(row["province_name"]),
        city_name=row["city_name"] if row["city_name"] not in (None, "") else None,
        area_name=row["area_name"] if row["area_name"] not in (None, "") else None,
        area_code=row["area_code"] if row["area_code"] not in (None, "") else None,
        longitude=None,
        latitude=None,
        keyword="",
        partition_code="",
        source_url="",
        source_name="dmfw",
        roman_alphabet_spelling="",
        ethnic_minorities_writing="",
        raw_payload_json="",
        match_mode="",
        fetched_at_utc="",
        captured_at=str(row["captured_at"]),
        updated_at=str(row["updated_at"]),
        geometry_type=str(row["geometry_type"]),
        coordinates_json=str(row["coordinates_json"]),
    )


def _ensure_dmfw_place_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(dmfw_places)").fetchall()}
    if "geometry_type" not in columns:
        conn.execute("ALTER TABLE dmfw_places ADD COLUMN geometry_type TEXT NOT NULL DEFAULT ''")
    if "coordinates_json" not in columns:
        conn.execute("ALTER TABLE dmfw_places ADD COLUMN coordinates_json TEXT NOT NULL DEFAULT ''")
    if "match_mode" not in columns:
        conn.execute("ALTER TABLE dmfw_places ADD COLUMN match_mode TEXT NOT NULL DEFAULT 'contain'")
    if "fetched_at_utc" not in columns:
        conn.execute("ALTER TABLE dmfw_places ADD COLUMN fetched_at_utc TEXT NOT NULL DEFAULT ''")
