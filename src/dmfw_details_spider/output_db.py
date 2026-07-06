"""worker 临时库 + 总库表结构 + 写入 + 汇总。"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

SQLITE_BUSY_TIMEOUT_MS = 30000
SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.25
T = TypeVar("T")

# ---- 表定义 ----

CREATE_PLACE_DETAILS_TABLE = """
CREATE TABLE IF NOT EXISTS place_details (
    id TEXT PRIMARY KEY,
    place_code TEXT,
    standard_name TEXT,
    old_name TEXT,
    place_type TEXT,
    place_type_code TEXT,
    province_name TEXT,
    city_name TEXT,
    area_name TEXT,
    province TEXT,
    city TEXT,
    area TEXT,
    roman_alphabet_spelling TEXT,
    ethnic_minorities_writing TEXT,
    place_origin TEXT,
    place_meaning TEXT,
    place_history TEXT,
    government_history TEXT,
    geometry_type TEXT,
    coordinates_json TEXT,
    gdm_json TEXT,
    raw_json TEXT NOT NULL,
    response_status_code INTEGER,
    fetched_at TEXT,
    worker_id TEXT,
    attempt INTEGER,
    error TEXT
)
"""

CREATE_PLACE_DETAILS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_place_details_place_code ON place_details(place_code)",
    "CREATE INDEX IF NOT EXISTS idx_place_details_standard_name ON place_details(standard_name)",
    "CREATE INDEX IF NOT EXISTS idx_place_details_place_type_code ON place_details(place_type_code)",
    "CREATE INDEX IF NOT EXISTS idx_place_details_province_city_area ON place_details(province, city, area)",
]

# 总库额外字段
CREATE_MASTER_PLACE_DETAILS_TABLE = """
CREATE TABLE IF NOT EXISTS place_details (
    id TEXT PRIMARY KEY,
    place_code TEXT,
    standard_name TEXT,
    old_name TEXT,
    place_type TEXT,
    place_type_code TEXT,
    province_name TEXT,
    city_name TEXT,
    area_name TEXT,
    province TEXT,
    city TEXT,
    area TEXT,
    roman_alphabet_spelling TEXT,
    ethnic_minorities_writing TEXT,
    place_origin TEXT,
    place_meaning TEXT,
    place_history TEXT,
    government_history TEXT,
    geometry_type TEXT,
    coordinates_json TEXT,
    gdm_json TEXT,
    raw_json TEXT NOT NULL,
    response_status_code INTEGER,
    fetched_at TEXT,
    worker_id TEXT,
    attempt INTEGER,
    error TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    source_run_id TEXT,
    source_worker_id TEXT,
    merge_at TEXT
)
"""

# ---- place_details 全部列名（id 除外，用于 UPSERT） ----

DETAIL_COLS = [
    "place_code", "standard_name", "old_name", "place_type", "place_type_code",
    "province_name", "city_name", "area_name", "province", "city", "area",
    "roman_alphabet_spelling", "ethnic_minorities_writing",
    "place_origin", "place_meaning", "place_history", "government_history",
    "geometry_type", "coordinates_json", "gdm_json",
    "raw_json", "response_status_code", "fetched_at",
    "worker_id", "attempt", "error",
]

MASTER_EXTRA_COLS = ["first_seen_at", "last_seen_at", "source_run_id", "source_worker_id", "merge_at"]


# ---- 工具函数 ----

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            logger.debug(f"output_db locked attempt={attempt}/{attempts}, retry in {delay_seconds}s")
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable retry state")


# ---- Worker 临时库 ----

class OutputDB:
    """Worker 临时输出库 —— 每个 worker 独占写入。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return _configure_connection(conn)

    def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        def _init() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                _configure_connection(conn)
                conn.execute(CREATE_PLACE_DETAILS_TABLE)
                for idx_sql in CREATE_PLACE_DETAILS_INDEXES:
                    conn.execute(idx_sql)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_init)

    def upsert_place(self, record: dict) -> None:
        cols = ["id"] + DETAIL_COLS
        values = [record.get(c) for c in cols]
        placeholders = ",".join("?" for _ in cols)
        col_names = ",".join(cols)

        set_clause = ",".join(f"{c}=excluded.{c}" for c in DETAIL_COLS)

        sql = (
            f"INSERT INTO place_details ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
        )

        def _upsert() -> None:
            conn = self._connect()
            try:
                conn.execute(sql, values)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_upsert)

    def bulk_upsert(self, records: list[dict]) -> None:
        """批量 upsert，单事务提交。"""
        if not records:
            return
        cols = ["id"] + DETAIL_COLS
        col_names = ",".join(cols)
        placeholders = ",".join("?" for _ in cols)
        set_clause = ",".join(f"{c}=excluded.{c}" for c in DETAIL_COLS)

        sql = (
            f"INSERT INTO place_details ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {set_clause}"
        )

        def _bulk() -> None:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for record in records:
                    values = [record.get(c) for c in cols]
                    conn.execute(sql, values)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        _run_with_locked_retry(_bulk)

    def count(self) -> int:
        def _count() -> int:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) as c FROM place_details").fetchone()["c"]
            finally:
                conn.close()

        return _run_with_locked_retry(_count)


# ---- 总库 ----

class MasterDB:
    """长期累加总库。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return _configure_connection(conn)

    def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        def _init() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                _configure_connection(conn)
                conn.execute(CREATE_MASTER_PLACE_DETAILS_TABLE)
                for idx_sql in CREATE_PLACE_DETAILS_INDEXES:
                    conn.execute(idx_sql)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_init)

    def count(self) -> int:
        def _count() -> int:
            conn = self._connect()
            try:
                return conn.execute("SELECT COUNT(*) as c FROM place_details").fetchone()["c"]
            finally:
                conn.close()

        return _run_with_locked_retry(_count)

    def upsert_place(self, record: dict, run_id: str) -> None:
        all_cols = ["id"] + DETAIL_COLS + MASTER_EXTRA_COLS
        now = _now_iso()

        values = []
        for c in all_cols:
            if c == "first_seen_at":
                values.append(record.get("first_seen_at", now))
            elif c in ("last_seen_at", "merge_at"):
                values.append(now)
            elif c == "source_run_id":
                values.append(run_id)
            elif c == "source_worker_id":
                values.append(record.get("worker_id", ""))
            else:
                values.append(record.get(c))

        placeholders = ",".join("?" for _ in all_cols)
        col_names = ",".join(all_cols)

        update_cols = DETAIL_COLS + ["last_seen_at", "source_run_id", "source_worker_id", "merge_at"]
        set_clause = ",".join(
            f"{c}=excluded.{c}" if c != "first_seen_at" else f"{c}=COALESCE(place_details.{c}, excluded.{c})"
            for c in update_cols
        )
        # first_seen_at: keep original if exists，只对额外列做特殊处理
        set_parts = []
        for c in DETAIL_COLS:
            set_parts.append(f"{c}=excluded.{c}")
        set_parts.append("last_seen_at=excluded.last_seen_at")
        set_parts.append("source_run_id=excluded.source_run_id")
        set_parts.append("source_worker_id=excluded.source_worker_id")
        set_parts.append("merge_at=excluded.merge_at")
        # first_seen_at: keep original
        set_parts.append("first_seen_at=COALESCE(place_details.first_seen_at, excluded.first_seen_at)")

        sql = (
            f"INSERT INTO place_details ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(set_parts)}"
        )

        def _upsert() -> None:
            conn = self._connect()
            try:
                conn.execute(sql, values)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_upsert)

    def bulk_upsert(self, records: list[dict], run_id: str) -> int:
        """批量 upsert 到总库，单事务提交。返回成功写入条数。"""
        if not records:
            return 0

        all_cols = ["id"] + DETAIL_COLS + MASTER_EXTRA_COLS
        col_names = ",".join(all_cols)
        placeholders = ",".join("?" for _ in all_cols)

        set_parts = []
        for c in DETAIL_COLS:
            set_parts.append(f"{c}=excluded.{c}")
        set_parts.append("last_seen_at=excluded.last_seen_at")
        set_parts.append("source_run_id=excluded.source_run_id")
        set_parts.append("source_worker_id=excluded.source_worker_id")
        set_parts.append("merge_at=excluded.merge_at")
        set_parts.append("first_seen_at=COALESCE(place_details.first_seen_at, excluded.first_seen_at)")

        sql = (
            f"INSERT INTO place_details ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(set_parts)}"
        )

        now = _now_iso()

        def _bulk() -> None:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for record in records:
                    values = []
                    for c in all_cols:
                        if c == "first_seen_at":
                            values.append(record.get("first_seen_at", now))
                        elif c in ("last_seen_at", "merge_at"):
                            values.append(now)
                        elif c == "source_run_id":
                            values.append(run_id)
                        elif c == "source_worker_id":
                            values.append(record.get("worker_id", ""))
                        else:
                            values.append(record.get(c))
                    conn.execute(sql, values)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        _run_with_locked_retry(_bulk)
        return len(records)


# ---- 汇总 ----

DEFAULT_MERGE_BATCH_SIZE = 5000


def merge_worker_db(
    worker_db_path: str,
    master_db: MasterDB,
    run_id: str,
    batch_size: int = DEFAULT_MERGE_BATCH_SIZE,
) -> dict:
    """读取一个 worker 临时库，分批 UPSERT 进总库。返回统计。"""
    if not os.path.exists(worker_db_path):
        return {"file": worker_db_path, "error": "文件不存在", "read": 0, "inserted": 0, "updated": 0}

    worker_conn = sqlite3.connect(f"file:{worker_db_path}?mode=ro", uri=True)
    worker_conn.row_factory = sqlite3.Row

    try:
        rows = worker_conn.execute("SELECT * FROM place_details").fetchall()
        before = master_db.count()
        errors = 0
        total_read = len(rows)

        for i in range(0, total_read, batch_size):
            batch = [dict(row) for row in rows[i:i + batch_size]]
            try:
                master_db.bulk_upsert(batch, run_id)
            except Exception:
                logger.warning(
                    f"批量 upsert 失败 (offset={i}, size={len(batch)})，"
                    f"逐条回退以隔离问题记录"
                )
                for record in batch:
                    try:
                        master_db.upsert_place(record, run_id)
                    except Exception as exc:
                        errors += 1
                        logger.error(f"merge 单条失败 id={record.get('id', '?')}: {exc}")

        after = master_db.count()
        inserted = max(0, after - before)

        return {
            "file": worker_db_path,
            "read": total_read,
            "inserted": inserted,
            "updated": total_read - inserted - errors,
            "skipped": 0,
            "errors": errors,
            "error": None,
        }
    except Exception as exc:
        return {"file": worker_db_path, "error": str(exc), "read": 0, "inserted": 0, "updated": 0}
    finally:
        worker_conn.close()


def merge_run_directory(
    run_dir: str,
    master_db: MasterDB,
    run_id: str,
    delete_after: bool = False,
    batch_size: int = DEFAULT_MERGE_BATCH_SIZE,
) -> dict:
    """扫描 run 目录下所有 worker_*.sqlite，分批汇总进总库。"""
    run_path = Path(run_dir)
    worker_files = sorted(run_path.glob("worker_*.sqlite"))
    if not worker_files:
        return {"scanned": 0, "total_read": 0, "total_inserted": 0, "total_updated": 0, "total_errors": 0, "results": []}

    total_read = 0
    total_inserted = 0
    total_updated = 0
    total_errors = 0
    results = []

    for wf in worker_files:
        logger.info(f"汇总 worker 库: {wf}")
        r = merge_worker_db(str(wf), master_db, run_id, batch_size=batch_size)
        results.append(r)
        if r.get("error"):
            logger.error(f"  失败: {r['error']}")
            total_errors += 1
        else:
            total_read += r["read"]
            total_inserted += r["inserted"]
            total_updated += r["updated"]
            total_errors += r.get("errors", 0)
            logger.info(f"  读取 {r['read']}, 新增 ~{r['inserted']}, 更新 ~{r['updated']}, 异常 {r.get('errors', 0)}")

            if delete_after and r.get("error") is None:
                try:
                    os.remove(str(wf))
                    logger.info(f"  已删除: {wf}")
                except OSError as exc:
                    logger.warning(f"  删除失败: {wf}: {exc}")

    return {
        "scanned": len(worker_files),
        "total_read": total_read,
        "total_inserted": total_inserted,
        "total_updated": total_updated,
        "total_errors": total_errors,
        "results": results,
    }
