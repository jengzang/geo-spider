"""共享进度库 —— id_tasks 表 + 原子领取 + 状态管理。"""

from __future__ import annotations

import logging
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

CREATE_ID_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS id_tasks (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_by TEXT,
    claimed_at TEXT,
    done_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT
)
"""

CREATE_ID_TASKS_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_id_tasks_status ON id_tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_id_tasks_claimed_at ON id_tasks(claimed_at)",
    "CREATE INDEX IF NOT EXISTS idx_id_tasks_updated_at ON id_tasks(updated_at)",
]


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
            logger.debug(f"state_db locked attempt={attempt}/{attempts}, retry in {delay_seconds}s")
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable retry state")


class StateDB:
    """共享进度库 —— 协调多 worker 任务分配。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = str(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        return _configure_connection(conn)

    def initialize(self) -> None:
        """创建表和索引。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        def _init() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                _configure_connection(conn)
                conn.execute(CREATE_ID_TASKS_TABLE)
                for idx_sql in CREATE_ID_TASKS_INDEXES:
                    conn.execute(idx_sql)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_init)

    # ------------------------------------------------------------------
    # ID 同步
    # ------------------------------------------------------------------

    def sync_ids(self, ids: object, batch_size: int = 5000) -> dict[str, int]:
        """批量 INSERT OR IGNORE，返回 {added, existed, total_in_file}。"""
        total = 0
        added = 0

        def _sync() -> None:
            nonlocal total, added
            conn = self._connect()
            try:
                batch: list[tuple[str, str, str]] = []
                for id_val in ids:
                    total += 1
                    now = _now_iso()
                    batch.append((str(id_val), "pending", now))
                    if len(batch) >= batch_size:
                        added += self._insert_batch(conn, batch)
                        batch.clear()
                if batch:
                    added += self._insert_batch(conn, batch)
            finally:
                conn.close()

        _run_with_locked_retry(_sync)
        existed = total - added
        return {"added": added, "existed": existed, "total_in_file": total}

    @staticmethod
    def _insert_batch(conn: sqlite3.Connection, batch: list[tuple[str, str, str]]) -> int:
        sql = "INSERT OR IGNORE INTO id_tasks (id, status, updated_at) VALUES (?, ?, ?)"
        prev = conn.total_changes
        conn.executemany(sql, batch)
        conn.commit()
        return conn.total_changes - prev

    # ------------------------------------------------------------------
    # 任务领取
    # ------------------------------------------------------------------

    def claim_batch(
        self, worker_id: str, batch_size: int, claim_timeout_minutes: int = 30
    ) -> list[str]:
        """原子事务领取一批 ID（pending + retry + failed + 超时 claimed）。"""
        from datetime import timedelta
        now = _now_iso()

        def _claim() -> list[str]:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cutoff_dt = datetime.now(timezone.utc) - timedelta(minutes=claim_timeout_minutes)
                cutoff = cutoff_dt.isoformat()
                # 领取优先级: pending > retry > failed > 超时 claimed
                sql = """
                    SELECT id FROM id_tasks
                    WHERE status IN ('pending', 'retry', 'failed')
                       OR (status = 'claimed' AND claimed_at < ?)
                    ORDER BY
                        CASE status
                            WHEN 'pending' THEN 0
                            WHEN 'retry' THEN 1
                            WHEN 'failed' THEN 2
                            WHEN 'claimed' THEN 3
                        END,
                        updated_at ASC
                    LIMIT ?
                """
                rows = conn.execute(sql, (cutoff, batch_size)).fetchall()
                if not rows:
                    conn.commit()
                    return []

                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" for _ in ids)
                update_sql = f"""
                    UPDATE id_tasks
                    SET status = 'claimed',
                        claimed_by = ?,
                        claimed_at = ?,
                        attempts = attempts + 1,
                        updated_at = ?
                    WHERE id IN ({placeholders})
                """
                conn.execute(update_sql, [worker_id, now, now] + ids)
                conn.commit()
                return ids
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return _run_with_locked_retry(_claim)

    # ------------------------------------------------------------------
    # 一次性分配（启动时用）
    # ------------------------------------------------------------------

    def iter_claimable_ids(self) -> object:
        """流式返回所有可领取 ID（pending/retry/failed），按优先级排序。

        生成器持有连接，调用方迭代完自动关闭。
        """
        conn = self._connect()
        sql = """SELECT id FROM id_tasks
                 WHERE status IN ('pending', 'retry', 'failed')
                 ORDER BY CASE status
                     WHEN 'pending' THEN 0
                     WHEN 'retry' THEN 1
                     WHEN 'failed' THEN 2
                 END, updated_at ASC"""
        try:
            for row in conn.execute(sql):
                yield row["id"]
        finally:
            conn.close()

    def bulk_claim(self, worker_id: str, ids: list[str]) -> None:
        """原子事务把一批 ID 标记为 claimed。"""
        if not ids:
            return
        now = _now_iso()

        def _claim() -> None:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.executemany(
                    "UPDATE id_tasks SET status='claimed', claimed_by=?, "
                    "claimed_at=?, attempts=attempts+1, updated_at=? "
                    "WHERE id=?",
                    [(worker_id, now, now, id_val) for id_val in ids],
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        _run_with_locked_retry(_claim)

    def release_all_claimed(self) -> int:
        """所有 claimed → pending。用于崩溃恢复和退出释放。返回释放数。"""
        now = _now_iso()

        def _release() -> int:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    "UPDATE id_tasks SET status='pending', claimed_by=NULL, "
                    "claimed_at=NULL, updated_at=? WHERE status='claimed'",
                    (now,),
                )
                count = cursor.rowcount
                conn.commit()
                return count
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return _run_with_locked_retry(_release)

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------

    def mark_done(self, id_val: str) -> None:
        now = _now_iso()

        def _mark() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE id_tasks SET status='done', done_at=?, updated_at=? WHERE id=?",
                    (now, now, str(id_val)),
                )
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_mark)

    def mark_retry(self, id_val: str, error: str) -> None:
        now = _now_iso()

        def _mark() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE id_tasks SET status='retry', last_error=?, updated_at=? WHERE id=?",
                    (error[:500], now, str(id_val)),
                )
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_mark)

    def mark_failed(self, id_val: str, error: str) -> None:
        now = _now_iso()

        def _mark() -> None:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE id_tasks SET status='failed', last_error=?, updated_at=? WHERE id=?",
                    (error[:500], now, str(id_val)),
                )
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_mark)

    # ------------------------------------------------------------------
    # 批量状态更新（减少锁竞争）
    # ------------------------------------------------------------------

    def bulk_mark_done(self, ids: list[str]) -> None:
        """批量标记 done —— 一次事务完成。"""
        if not ids:
            return
        now = _now_iso()

        def _mark() -> None:
            conn = self._connect()
            try:
                placeholders = ",".join("?" for _ in ids)
                sql = f"UPDATE id_tasks SET status='done', done_at=?, updated_at=? WHERE id IN ({placeholders})"
                conn.execute(sql, [now, now] + ids)
                conn.commit()
            finally:
                conn.close()

        _run_with_locked_retry(_mark)

    def bulk_mark_status(self, updates: list[tuple[str, str, str]]) -> None:
        """批量更新状态。每项: (id, status, error_text)。
        status 为 'retry' 或 'failed'。"""
        if not updates:
            return
        now = _now_iso()

        def _mark() -> None:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                for id_val, status, error in updates:
                    conn.execute(
                        "UPDATE id_tasks SET status=?, last_error=?, updated_at=? WHERE id=?",
                        (status, error[:500], now, str(id_val)),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        _run_with_locked_retry(_mark)

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, int]:
        def _stats() -> dict[str, int]:
            conn = self._connect()
            try:
                total = conn.execute("SELECT COUNT(*) as c FROM id_tasks").fetchone()["c"]
                rows = conn.execute(
                    "SELECT status, COUNT(*) as c FROM id_tasks GROUP BY status"
                ).fetchall()
                stats = {"total": total}
                for row in rows:
                    stats[row["status"]] = row["c"]
                for s in ("pending", "claimed", "done", "retry", "failed"):
                    stats.setdefault(s, 0)
                return stats
            finally:
                conn.close()

        return _run_with_locked_retry(_stats)

    def get_last_updated(self) -> str | None:
        def _last() -> str | None:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT MAX(updated_at) as t FROM id_tasks"
                ).fetchone()
                return row["t"] if row else None
            finally:
                conn.close()

        return _run_with_locked_retry(_last)
