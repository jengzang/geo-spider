from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import json
import logging
import multiprocessing as mp
import os
import signal
import shutil
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from dmfw_places_spider.config.settings import Settings
from dmfw_places_spider.crawler.profile import RequestProfile
from dmfw_places_spider.crawler.proxies import StaticProxyProvider
from dmfw_places_spider.crawler.session import SpiderSession
from dmfw_places_spider.exporters.csv_exporter import CsvExporter
from dmfw_places_spider.exporters.excel_exporter import ExcelExporter
from dmfw_places_spider.exporters.json_exporter import JsonExporter
from dmfw_places_spider.models.place import DmfwDivision, DmfwPlaceRecord
from dmfw_places_spider.models.region import CrawlRunRecord, utc_now_iso
from dmfw_places_spider.storage.sqlite import SQLiteDivisionRepository, SQLitePlaceRepository, SQLiteTotalPlaceRepository


MAX_PARALLEL_DMFW_WORKERS = 8


class GracefulStopRequested(Exception):
    """父进程请求 worker 优雅停止。"""


def _stop_requested(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _check_stop(stop_event):
    if _stop_requested(stop_event):
        raise GracefulStopRequested()


def _init_worker_ignore_sigint():
    """子进程忽略 Ctrl+C。

    Ctrl+C 只由父进程处理。
    否则当某个 worker 已经完成任务、回到 ProcessPoolExecutor 内部等待队列时，
    它可能在 call_queue.get() 处被 KeyboardInterrupt 打断，导致 BrokenProcessPool。
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)


@dataclass(slots=True)
class DmfwRunOptions:
    chars: str
    export_formats: list[str]
    resume: bool = False
    match_mode: str = "contain"
    search_type: str = "模糊"
    province_codes: list[str] | None = None
    flush_batch_size: int = 1000
    max_runtime_seconds: int | None = None
    sync_divisions_first: bool = False
    json_path: str | None = None
    write_run_db: bool = True
    write_total_db: bool = False
    total_db_path: str | None = None
    skip_export: bool = False
    # Parallel worker/logging label. It is None for normal single-task runs.
    task_namespace: str | None = None


class DmfwApiClient:
    def __init__(self, base_url: str, session: SpiderSession, *, bypass_env_proxy: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session
        self.session.session.trust_env = not bypass_env_proxy

    def list_divisions(self, code: str) -> list[DmfwDivision]:
        response = self.session.get(
            f"{self.base_url}/xzqh/getList",
            params={"code": code, "trimCode": "true", "maxdeep": "1"},
        )
        payload = response.json()
        rows = _extract_rows(payload)
        divisions: list[DmfwDivision] = []
        for row in rows:
            divisions.append(
                DmfwDivision(
                    code=str(row.get("code", "")),
                    name=str(row.get("name", "")),
                    parent_code=str(row.get("parentCode", code)),
                    level=str(row.get("level", _infer_division_level(str(row.get("code", ""))))),
                )
            )
        return [division for division in divisions if division.code]

    def search_places(
        self,
        *,
        keyword: str,
        code: str,
        page: int = 1,
        size: int = 100,
        place_type_code: str = "",
        year: int = 0,
        search_type: str = "模糊",
    ) -> dict[str, object]:
        response = self.session.get(
            f"{self.base_url}/stname/listPub",
            params={
                "stName": keyword,
                "placeTypeCode": place_type_code,
                "code": code,
                "page": str(page),
                "size": str(size),
                "year": str(year),
                "searchType": search_type,
            },
        )
        payload = response.json()
        records = _extract_records(payload)
        total = _extract_total(payload, len(records))
        return {"total": total, "records": records}


@dataclass(slots=True)
class DmfwProgressTracker:
    path: Path
    chars: str
    resume: bool
    _state: dict[str, object] = field(init=False, repr=False, default_factory=dict)
    _completed_set: set[str] = field(init=False, repr=False, default_factory=set)
    _dirty: bool = field(init=False, repr=False, default=False)
    _pending_count: int = field(init=False, repr=False, default=0)
    _write_threshold: int = field(init=False, repr=False, default=1)
    _shared_path: Path | None = field(init=False, repr=False, default=None)
    _shared_lock: object = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        if self.resume and self.path.exists():
            self._state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._state = {"chars": self.chars, "completed": []}
        completed = self._state.get("completed", [])
        if isinstance(completed, list):
            self._completed_set = {str(item) for item in completed}
        else:
            self._completed_set = set()
        self._state["completed"] = list(completed) if isinstance(completed, list) else []
        self._dirty = False
        self._pending_count = 0
        self._write_threshold = 500 if len(self.chars) > 100 else 1
        if self.resume:
            self._import_other_progress()
        if not (self.resume and self.path.exists()):
            self._dirty = True
            self.save()

    def _import_other_progress(self) -> None:
        filename = self.path.name
        if not filename.startswith("dmfw_chars_"):
            return
        name_part = filename.split(".progress.json")[0]
        parts = name_part.split("_")
        if len(parts) < 4:
            return
        match_mode = parts[-2]
        province_suffix = parts[-1]

        parent_dir = self.path.parent
        if not parent_dir.exists():
            return

        patterns = [
            f"dmfw_chars_*_{match_mode}_{province_suffix}.progress.json"
        ]
        
        # Legacy progress files (dmfw_chars_村.progress.json) default to contain and all
        if match_mode == "contain" and province_suffix == "all":
            patterns.append("dmfw_chars_*.progress.json")

        imported_tokens = set()
        for pattern in patterns:
            for other_file in parent_dir.glob(pattern):
                if other_file.resolve() == self.path.resolve():
                    continue
                if pattern == "dmfw_chars_*.progress.json":
                    other_name_part = other_file.name.split(".progress.json")[0]
                    other_parts = other_name_part.split("_")
                    if len(other_parts) >= 4:
                        continue
                
                try:
                    other_data = json.loads(other_file.read_text(encoding="utf-8"))
                    other_completed = other_data.get("completed", [])
                    if isinstance(other_completed, list):
                        for token in other_completed:
                            token_str = str(token)
                            if token_str not in self._completed_set:
                                imported_tokens.add(token_str)
                except Exception as e:
                    logger.warning(f"Failed to import progress from {other_file}: {e}")

        if imported_tokens:
            self._completed_set.update(imported_tokens)
            self._state["completed"] = list(self._completed_set)
            self._dirty = True
            logger.info(f"Imported {len(imported_tokens)} completed partitions from other progress files.")
            self.save()

    def is_completed(self, keyword: str, code: str) -> bool:
        return f"{keyword}|{code}" in self._completed_set

    def mark_completed(self, keyword: str, code: str) -> None:
        token = f"{keyword}|{code}"
        if token not in self._completed_set:
            self._completed_set.add(token)
            self._state["completed"].append(token)
            self._dirty = True
            self._pending_count += 1
            if self._pending_count >= self._write_threshold:
                self.save()

    def set_shared_progress(self, path: Path, lock) -> None:
        self._shared_path = path
        self._shared_lock = lock
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self._merge_from_shared(data)
            # 强制 save：共享文件不存在时创建它，有新导入时推进本地文件
            if not path.exists() or self._dirty:
                self._dirty = True
                self.save()
        except Exception:
            pass

    def _merge_from_shared(self, data: dict) -> None:
        own_chars = set(self.chars.replace("\n", "").replace("\r", ""))
        completed = data.get("completed", [])
        if not isinstance(completed, list):
            return
        imported = 0
        for token in completed:
            token_str = str(token)
            if token_str in self._completed_set:
                continue
            keyword = token_str.split("|")[0]
            if keyword not in own_chars:
                continue
            self._completed_set.add(token_str)
            imported += 1
        if imported:
            self._state["completed"] = list(self._completed_set)
            self._dirty = True
            logger.info(
                f"Imported {imported} completed partitions from shared progress."
            )

    def save(self) -> None:
        if not self._dirty:
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if self._shared_path is not None and self._shared_lock is not None:
            with self._shared_lock:
                try:
                    if self._shared_path.exists():
                        shared = json.loads(
                            self._shared_path.read_text(encoding="utf-8")
                        )
                        logger.info(
                            "[SHARED_SYNC] read shared progress: "
                            f"shared_tokens={len(shared.get('completed', []))} "
                            f"local_tokens={len(self._completed_set)}"
                        )
                    else:
                        shared = {"completed": []}
                        logger.info(
                            "[SHARED_SYNC] shared progress file not found, creating new."
                        )

                    shared_completed = shared.get("completed", [])
                    shared_set = (
                        {str(t) for t in shared_completed}
                        if isinstance(shared_completed, list)
                        else set()
                    )

                    merged = shared_set | self._completed_set
                    new_local = len(merged) - len(shared_set)

                    self._merge_from_shared({"completed": list(shared_set)})

                    shared["completed"] = sorted(merged)
                    self._shared_path.parent.mkdir(parents=True, exist_ok=True)
                    self._shared_path.write_text(
                        json.dumps(shared, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        "[SHARED_SYNC] wrote shared progress: "
                        f"total_tokens={len(merged)} new_from_this_worker={new_local}"
                    )
                except Exception:
                    pass

        self._dirty = False
        self._pending_count = 0


def sync_dmfw_divisions(*, settings: Settings) -> dict[str, object]:
    repository = SQLiteDivisionRepository(settings.sqlite_path)
    repository.initialize()
    client = _build_dmfw_api_client(settings)
    divisions = _sync_division_subtree(
        client=client,
        division_repository=repository,
        code="0",
    )
    root_divisions = repository.list_divisions(parent_code="0")
    return {
        "source_name": "dmfw",
        "division_count": len(divisions),
        "codes": [division.code for division in root_divisions],
    }


def run_dmfw_chars_pipeline(*, settings: Settings, options: DmfwRunOptions, stop_event=None, shared_progress_path=None, shared_lock=None) -> dict[str, object]:
    task_name = options.task_namespace or "single"
    task_label = f"task={task_name}"

    division_repository = SQLiteDivisionRepository(settings.sqlite_path)
    division_repository.initialize()
    repository = SQLitePlaceRepository(settings.sqlite_path)
    repository.initialize()
    total_repository: SQLiteTotalPlaceRepository | None = None
    total_db_path: Path | None = None
    if options.write_total_db:
        total_db_path = Path(options.total_db_path) if options.total_db_path else settings.processed_dir / "dmfw_places_total.db"
        total_repository = SQLiteTotalPlaceRepository(total_db_path)
        total_repository.initialize()

    if options.sync_divisions_first:
        sync_dmfw_divisions(settings=settings)

    client = _build_dmfw_api_client(settings)
    province_divisions = _get_cached_divisions(
        client=client,
        division_repository=division_repository,
        code="0",
    )
    if not province_divisions:
        raise RuntimeError("省级区划缓存为空，请先运行区划同步或启用 sync_divisions_first=True")
    if options.province_codes:
        allowed = set(options.province_codes)
        province_divisions = [division for division in province_divisions if division.code in allowed]

    division_names: dict[str, str] = {}
    if settings.sqlite_path.exists():
        try:
            import sqlite3
            with sqlite3.connect(settings.sqlite_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dmfw_divisions'")
                if cursor.fetchone():
                    rows = conn.execute("SELECT code, name FROM dmfw_divisions").fetchall()
                    division_names = {row["code"]: row["name"] for row in rows}
        except Exception:
            pass

    for div in province_divisions:
        division_names[div.code] = div.name
    division_names[""] = "全国"

    normalized_chars = _normalize_chars(options.chars)
    unique_count = len(normalized_chars)
    display_chars = options.chars.replace("\n", " ").replace("\r", " ")
    display_chars = display_chars[:50] + "..." if len(display_chars) > 50 else display_chars
    crawl_scope = "指定省份" if options.province_codes else "全国优先"
    logger.info(
        f"{task_label} 开始抓取地名任务，匹配模式: {options.match_mode}，抓取范围: {crawl_scope}，"
        f"待处理字符: {display_chars} (共 {unique_count} 个去重汉字)，"
        f"可用省级区划数: {len(province_divisions)}"
    )
    if options.resume:
        logger.info("已启用断点续传模式 (resume)")

    progress = DmfwProgressTracker(
        path=settings.raw_dir / _build_progress_filename(options.chars, options.match_mode, options.province_codes),
        chars=options.chars,
        resume=options.resume,
    )

    if shared_progress_path is not None and shared_lock is not None:
        progress.set_shared_progress(shared_progress_path, shared_lock)

    requested_formats = _normalize_formats(options.export_formats or ["db"])
    db_only_export = set(requested_formats) == {"db"}
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    started_at = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    flush_count = 0
    persisted_total = 0
    fetched_total = 0
    current_char = ""
    current_char_index = 0
    completed_chars = 0
    db_write_total_seconds = 0.0
    db_write_total_rows = 0
    last_batch_size = 0
    progress_context: dict[str, object] = {
        "current_keyword": "",
        "current_code": "",
        "current_name": "",
        "current_token": "",
        "last_completed_keyword": "",
        "last_completed_code": "",
        "last_completed_name": "",
        "last_completed_token": "",
    }
    deduped: dict[str, DmfwPlaceRecord] = {}
    division_children_cache: dict[str, list[DmfwDivision]] = {}
    if not options.province_codes:
        division_children_cache[""] = province_divisions
    for division in province_divisions:
        cached_children = division_repository.list_divisions(parent_code=division.code)
        if cached_children:
            division_children_cache[division.code] = cached_children

    def persist_batch(batch: list[DmfwPlaceRecord], *, reason: str) -> float:
        nonlocal flush_count, db_write_total_seconds, db_write_total_rows, last_batch_size

        batch_size = len(batch)
        last_batch_size = batch_size
        write_started = time.monotonic()
        if options.write_run_db:
            repository.upsert_places(batch)
        if total_repository is not None:
            print(f"[DB_WRITE_START] pid={os.getpid()} {task_label} batch={batch_size} reason={reason}", flush=True)
            total_repository.upsert_places(batch)
            print(f"[DB_WRITE_DONE] pid={os.getpid()} {task_label} batch={batch_size} reason={reason}", flush=True)
        write_elapsed = time.monotonic() - write_started
        db_write_total_seconds += write_elapsed
        db_write_total_rows += batch_size
        flush_count += 1
        return write_elapsed

    def emit_exit_summary(*, status: str, error: BaseException | None = None) -> None:
        elapsed_seconds = max(time.monotonic() - started_monotonic, 0.000001)
        fetched_per_hour = fetched_total / elapsed_seconds * 3600
        fetched_per_minute = fetched_total / elapsed_seconds * 60
        avg_batch_size = db_write_total_rows / flush_count if flush_count else 0.0
        avg_db_write_seconds = db_write_total_seconds / flush_count if flush_count else 0.0
        province_part = ",".join(division.code for division in province_divisions) if options.province_codes else "all"

        total_chars = unique_count
        safe_total_chars = max(1, total_chars)
        active_char_index = current_char_index if current_char_index else completed_chars
        active_char = current_char if current_char else "<none>"
        is_char_in_progress = bool(current_char and completed_chars < current_char_index)
        active_progress_percent = active_char_index / safe_total_chars * 100
        completed_progress_percent = completed_chars / safe_total_chars * 100
        remaining_chars = max(0, total_chars - completed_chars)

        current_partition_keyword = str(progress_context.get("current_keyword") or "")
        current_partition_code = str(progress_context.get("current_code") or "")
        current_partition_name = str(progress_context.get("current_name") or "")
        current_partition_token = str(progress_context.get("current_token") or "")
        last_completed_keyword = str(progress_context.get("last_completed_keyword") or "")
        last_completed_code = str(progress_context.get("last_completed_code") or "")
        last_completed_name = str(progress_context.get("last_completed_name") or "")
        last_completed_token = str(progress_context.get("last_completed_token") or "")

        error_type = type(error).__name__ if error is not None else ""
        error_message = str(error) if error is not None else ""
        total_db_path_text = str(total_db_path) if total_db_path is not None else ""

        summary_lines = [
            "[WORKER_SUMMARY_BEGIN]",
            f"  status          : {status}",
            f"  pid             : {os.getpid()}",
            f"  task            : {task_name}",
            f"  run_id          : {run_id}",
            f"  elapsed         : {_format_duration(elapsed_seconds)} ({elapsed_seconds:.2f}s)",
            "",
            "  [char_progress]",
            f"  total_chars     : {total_chars}",
            f"  current_char    : {active_char!r}",
            f"  current_index   : {active_char_index}/{total_chars} ({active_progress_percent:.2f}%)",
            f"  completed_chars : {completed_chars}/{total_chars} ({completed_progress_percent:.2f}%)",
            f"  remaining_chars : {remaining_chars}",
            f"  in_progress     : {is_char_in_progress}",
            "",
            "  [partition_progress]",
            f"  current_keyword : {current_partition_keyword!r}",
            f"  current_code    : {current_partition_code!r}",
            f"  current_name    : {current_partition_name!r}",
            f"  current_token   : {current_partition_token!r}",
            f"  last_done_key   : {last_completed_keyword!r}",
            f"  last_done_code  : {last_completed_code!r}",
            f"  last_done_name  : {last_completed_name!r}",
            f"  last_done_token : {last_completed_token!r}",
            "",
            "  [throughput]",
            f"  fetched_total   : {fetched_total}",
            f"  fetched_rate    : {fetched_per_hour:.2f}/hour | {fetched_per_minute:.2f}/minute",
            f"  pending_memory  : {len(deduped)}",
            "",
            "  [db_write]",
            f"  flush_count     : {flush_count}",
            f"  db_write_rows   : {db_write_total_rows}",
            f"  last_batch_size : {last_batch_size}",
            f"  avg_batch_size  : {avg_batch_size:.2f}",
            f"  total_write_sec : {db_write_total_seconds:.3f}",
            f"  avg_write_sec   : {avg_db_write_seconds:.3f}",
            "",
            "  [options]",
            f"  match_mode      : {options.match_mode}",
            f"  search_type     : {options.search_type}",
            f"  province_codes  : {province_part}",
            f"  write_run_db    : {options.write_run_db}",
            f"  write_total_db  : {options.write_total_db}",
            f"  total_db_path   : {total_db_path_text}",
        ]
        if error is not None:
            summary_lines.extend([
                "",
                "  [error]",
                f"  error_type      : {error_type}",
                f"  error_message   : {error_message!r}",
            ])
        summary_lines.append("[WORKER_SUMMARY_END]")

        print("\n".join(summary_lines), flush=True)

    try:
        for current_char_index, char in enumerate(normalized_chars, start=1):
            _check_stop(stop_event)
            current_char = char
            initial_divisions = province_divisions if options.province_codes else [
                DmfwDivision(code="", name="全国", parent_code="", level="country")
            ]
            for division in initial_divisions:
                _check_stop(stop_event)
                for place in _iter_collect_partition(
                    client=client,
                    keyword=char,
                    code=division.code,
                    progress_tracker=progress,
                    division_repository=division_repository,
                    partition_threshold=settings.dmfw_partition_threshold,
                    page_size=settings.dmfw_page_size,
                    search_type=options.search_type,
                    match_mode=options.match_mode,
                    started_monotonic=started_monotonic,
                    max_runtime_seconds=options.max_runtime_seconds,
                    division_names=division_names,
                    division_children_cache=division_children_cache,
                    progress_context=progress_context,
                    stop_event=stop_event,
                ):
                    deduped[place.source_id] = place
                    fetched_total += 1
                    if len(deduped) >= options.flush_batch_size:
                        batch = list(deduped.values())
                        write_elapsed = persist_batch(batch, reason="periodic")
                        logger.info(
                            f"{task_label} 已批量写入 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                            f"累计写入批次数: {flush_count}，本次写入耗时: {write_elapsed:.3f}s"
                        )
                        deduped.clear()
                        _check_stop(stop_event)
            completed_chars = current_char_index
        
        if deduped:
            batch = list(deduped.values())
            write_elapsed = persist_batch(batch, reason="final")
            logger.info(
                f"{task_label} 已批量写入最后一批 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                f"累计写入批次数: {flush_count}，本次写入耗时: {write_elapsed:.3f}s"
            )
            deduped.clear()

        sqlite_export_path = settings.sqlite_path if options.write_run_db else (total_db_path or settings.sqlite_path)
        if options.write_run_db:
            persisted_total = repository.count_places()
        elif total_repository is not None:
            persisted_total = total_repository.count_places()
        else:
            persisted_total = 0

        if db_only_export:
            stored_places: list[DmfwPlaceRecord] = []
            place_count = persisted_total
        elif options.write_run_db:
            stored_places = repository.list_places()
            place_count = len(stored_places)
        elif total_repository is not None:
            stored_places = total_repository.list_places()
            place_count = len(stored_places)
        else:
            stored_places = []
            place_count = 0

        exported = (
            {}
            if options.skip_export
            else export_dmfw_places(
                records=stored_places,
                export_dir=settings.export_dir,
                sqlite_path=sqlite_export_path,
                formats=requested_formats,
            )
        )
        finished_at = datetime.now(UTC).isoformat()
        if options.write_run_db:
            repository.record_crawl_run(
                CrawlRunRecord(
                    run_id=run_id,
                    source_name="dmfw",
                    status="success",
                    item_count=place_count,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            )
        progress.save()
        logger.info(
            f"{task_label} 抓取任务顺利完成。累计抓取地名数: {fetched_total}，"
            f"数据库已保存总数: {persisted_total}，累计写入批次数: {flush_count}"
        )
        emit_exit_summary(status="success")
    except BaseException as exc:
        # During shutdown, finish the final DB flush and summary before accepting another Ctrl+C.
        # This prevents half-printed DB_WRITE_START logs and keeps progress behind DB writes.
        old_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            if deduped:
                batch = list(deduped.values())
                write_elapsed = persist_batch(batch, reason="exception_final")
                logger.info(
                    f"{task_label} 异常退出前：已批量写入最后一批 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                    f"累计写入批次数: {flush_count}，本次写入耗时: {write_elapsed:.3f}s"
                )
                deduped.clear()
            try:
                progress.save()
            except Exception as save_exc:
                logger.warning(f"{task_label} 异常退出时保存进度文件失败: {save_exc}")
            finished_at = datetime.now(UTC).isoformat()
            if options.write_run_db:
                repository.record_crawl_run(
                    CrawlRunRecord(
                        run_id=run_id,
                        source_name="dmfw",
                        status="failed",
                        item_count=repository.count_places(),
                        started_at=started_at,
                        finished_at=finished_at,
                        error_message=str(exc),
                    )
                )
            if isinstance(exc, GracefulStopRequested):
                emit_exit_summary(status="interrupted", error=exc)
            else:
                emit_exit_summary(status="failed", error=exc)
        finally:
            signal.signal(signal.SIGINT, old_sigint_handler)
        if isinstance(exc, GracefulStopRequested):
            logger.info(f"{task_label} 抓取任务收到优雅停止请求，已完成最后写库、进度保存和 summary 输出。")
            return {
                "run_id": run_id,
                "place_count": persisted_total,
                "persisted_count": persisted_total,
                "flush_count": flush_count,
                "source_name": "dmfw",
                "match_mode": options.match_mode,
                "province_codes": [division.code for division in province_divisions],
                "exported_files": {},
                "task_json": options.json_path,
                "task_namespace": options.task_namespace,
                "write_run_db": options.write_run_db,
                "write_total_db": options.write_total_db,
                "total_db_path": str(total_db_path) if total_db_path is not None else None,
                "status": "interrupted",
                "error_type": type(exc).__name__,
            }
        if isinstance(exc, KeyboardInterrupt):
            logger.info(f"{task_label} 抓取任务收到 Ctrl+C，已完成最后写库、进度保存和 summary 输出。")
        else:
            logger.error(f"{task_label} 抓取任务遇到异常中断: {exc}", exc_info=True)
        raise

    return {
        "run_id": run_id,
        "place_count": place_count,
        "persisted_count": persisted_total,
        "flush_count": flush_count,
        "source_name": "dmfw",
        "match_mode": options.match_mode,
        "province_codes": [division.code for division in province_divisions],
        "exported_files": exported,
        "task_json": options.json_path,
        "task_namespace": options.task_namespace,
        "write_run_db": options.write_run_db,
        "write_total_db": options.write_total_db,
        "total_db_path": str(total_db_path) if total_db_path is not None else None,
    }


def run_dmfw_parallel_tasks(*, settings: Settings, task_options: list[DmfwRunOptions], workers: int) -> dict[str, object]:
    if len(task_options) < 2:
        raise ValueError("parallel dmfw mode requires at least two task options")

    export_formats = _validate_parallel_task_options(settings, task_options)

    total_db_path = _resolve_total_db_path(settings, task_options[0])
    SQLiteTotalPlaceRepository(total_db_path).initialize()

    effective_workers = min(max(1, workers), len(task_options), MAX_PARALLEL_DMFW_WORKERS)
    manager = mp.Manager()
    stop_event = manager.Event()
    ctx = mp.get_context("spawn")
    shared_progress_path = _build_shared_progress_path(settings, task_options[0])
    shared_lock = manager.Lock()
    future_to_task: dict[object, DmfwRunOptions] = {}
    results: list[dict[str, object]] = []
    finished_task_namespaces: set[str] = set()
    interrupted = False

    with ProcessPoolExecutor(
        max_workers=effective_workers,
        mp_context=ctx,
        initializer=_init_worker_ignore_sigint,
    ) as executor:
        for option in task_options:
            task_namespace = _build_task_namespace(option)
            future = executor.submit(
                _run_dmfw_parallel_task_worker,
                settings,
                option,
                task_namespace,
                stop_event,
                shared_progress_path,
                shared_lock,
            )
            future_to_task[future] = option

        try:
            pending = set(future_to_task.keys())

            while pending:
                done, pending = wait(
                    pending,
                    timeout=1,
                    return_when=FIRST_COMPLETED,
                )

                for future in done:
                    task = future_to_task[future]
                    task_name = _build_task_namespace(task)

                    try:
                        result = future.result()
                    except Exception as exc:
                        print(
                            f"[PARALLEL_WORKER_FINISHED] task={task_name} "
                            f"status=failed error_type={type(exc).__name__} "
                            f"error={exc}",
                            flush=True,
                        )
                        continue

                    result_task_name = (
                        result.get("task_namespace")
                        or result.get("task")
                        or task_name
                    )

                    if result_task_name not in finished_task_namespaces:
                        results.append(result)
                        finished_task_namespaces.add(result_task_name)

                    status = result.get("status", "success")
                    print(
                        f"[PARALLEL_WORKER_FINISHED] task={result_task_name} status={status}",
                        flush=True,
                    )

        except KeyboardInterrupt:
            interrupted = True
            print(
                "[PARALLEL_INTERRUPT] Ctrl+C received; "
                "asking workers to flush final batches and summaries...",
                flush=True,
            )

            stop_event.set()

            pending = {
                future
                for future in future_to_task
                if not future.done()
            }

            try:
                while pending:
                    done, pending = wait(
                        pending,
                        timeout=1,
                        return_when=FIRST_COMPLETED,
                    )

                    for future in done:
                        task = future_to_task[future]
                        task_name = _build_task_namespace(task)

                        try:
                            result = future.result()
                        except Exception as exc:
                            print(
                                f"[PARALLEL_WORKER_FINISHED] task={task_name} "
                                f"status=failed error_type={type(exc).__name__} "
                                f"error={exc}",
                                flush=True,
                            )
                            continue

                        result_task_name = (
                            result.get("task_namespace")
                            or result.get("task")
                            or task_name
                        )

                        if result_task_name not in finished_task_namespaces:
                            results.append(result)
                            finished_task_namespaces.add(result_task_name)

                        status = result.get("status", "interrupted")
                        error_type = result.get("error_type")

                        if error_type:
                            print(
                                f"[PARALLEL_WORKER_FINISHED] task={result_task_name} "
                                f"status={status} error_type={error_type}",
                                flush=True,
                            )
                        else:
                            print(
                                f"[PARALLEL_WORKER_FINISHED] task={result_task_name} "
                                f"status={status}",
                                flush=True,
                            )

            except KeyboardInterrupt:
                print(
                    "[PARALLEL_FORCE_EXIT] second Ctrl+C received; "
                    "workers may not finish final flush.",
                    flush=True,
                )
                raise

        finally:
            if interrupted:
                print(
                    "[PARALLEL_INTERRUPT_DONE] all active workers finished final flush and summaries.",
                    flush=True,
                )

    total_repository = SQLiteTotalPlaceRepository(total_db_path)
    total_repository.initialize()
    persisted_total = total_repository.count_places()
    db_only_export = set(export_formats) == {"db"}
    stored_places = [] if db_only_export else total_repository.list_places()
    exported = (
        {}
        if interrupted
        else export_dmfw_places(
            records=stored_places,
            export_dir=settings.export_dir,
            sqlite_path=total_db_path,
            formats=export_formats,
        )
    )

    return {
        "mode": "parallel",
        "interrupted": interrupted,
        "task_count": len(task_options),
        "workers": effective_workers,
        "max_supported_workers": MAX_PARALLEL_DMFW_WORKERS,
        "place_count": persisted_total if db_only_export else len(stored_places),
        "persisted_count": persisted_total,
        "total_db_path": str(total_db_path),
        "exported_files": exported,
        "tasks": sorted(results, key=lambda item: str(item.get("task_json") or "")),
    }


def _run_dmfw_parallel_task_worker(settings: Settings, options: DmfwRunOptions, task_namespace: str, stop_event=None, shared_progress_path=None, shared_lock=None) -> dict[str, object]:
    worker_settings = replace(settings, raw_dir=settings.raw_dir / task_namespace)
    worker_options = replace(
        options,
        write_run_db=False,
        skip_export=True,
        sync_divisions_first=False,
        task_namespace=task_namespace,
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] pid=%(process)d %(name)s: %(message)s",
        force=True,
    )
    print(f"[WORKER_START] pid={os.getpid()} task={task_namespace}", flush=True)
    return run_dmfw_chars_pipeline(
        settings=worker_settings,
        options=worker_options,
        stop_event=stop_event,
        shared_progress_path=shared_progress_path,
        shared_lock=shared_lock,
    )


def _build_dmfw_api_client(settings: Settings) -> DmfwApiClient:
    profile = RequestProfile(
        timeout=settings.request_timeout,
        retries=settings.request_retries,
        sleep_min_seconds=settings.sleep_min_seconds,
        sleep_max_seconds=settings.sleep_max_seconds,
        backoff_base_seconds=settings.backoff_base_seconds,
        use_proxy=settings.proxy_enabled,
    )
    session = SpiderSession(
        profile,
        proxy_provider=StaticProxyProvider(settings.proxy_pool or []),
    )
    return DmfwApiClient(
        settings.dmfw_base_url,
        session=session,
        bypass_env_proxy=settings.dmfw_bypass_env_proxy,
    )


def _validate_parallel_task_options(settings: Settings, task_options: list[DmfwRunOptions]) -> list[str]:
    export_formats = _normalize_formats(task_options[0].export_formats or ["db"])
    total_db_path = _resolve_total_db_path(settings, task_options[0])
    for option in task_options:
        if not option.write_total_db:
            raise ValueError("parallel dmfw tasks require write_total_db=True for every task")
        if _normalize_formats(option.export_formats or ["db"]) != export_formats:
            raise ValueError("parallel dmfw tasks must use the same export formats")
        if _resolve_total_db_path(settings, option) != total_db_path:
            raise ValueError("parallel dmfw tasks must use the same total_db_path")
    return export_formats
def _resolve_total_db_path(settings: Settings, options: DmfwRunOptions) -> Path:
    if options.total_db_path:
        return Path(options.total_db_path)
    return settings.processed_dir / "dmfw_places_total.db"


def _build_task_namespace(options: DmfwRunOptions) -> str:
    if options.json_path:
        stem = Path(options.json_path).stem.strip()
        safe = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in stem)
        safe = safe.strip("-_")
        if safe:
            return safe
    return f"task-{abs(hash((options.chars, options.match_mode, tuple(options.province_codes or []))))}"


def _format_duration(seconds: float) -> str:
    seconds_int = max(0, int(seconds))
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def export_dmfw_places(
    *,
    records: list[DmfwPlaceRecord],
    export_dir: Path,
    sqlite_path: Path,
    formats: list[str],
) -> dict[str, str]:
    export_dir.mkdir(parents=True, exist_ok=True)
    requested = _normalize_formats(formats)
    exported: dict[str, str] = {}

    if "json" in requested:
        path = JsonExporter().export(records, export_dir / "dmfw_places.json")
        exported["json"] = str(path)
    if "csv" in requested:
        path = CsvExporter().export(records, export_dir / "dmfw_places.csv")
        exported["csv"] = str(path)
    if "xlsx" in requested:
        path = ExcelExporter().export(records, export_dir / "dmfw_places.xlsx")
        exported["xlsx"] = str(path)
    if "db" in requested:
        destination = export_dir / "dmfw_places.db"
        if destination.exists():
            destination.unlink()
        sqlite_export_path = sqlite_path
        wal_path = sqlite_path.with_name(f"{sqlite_path.name}-wal")
        shm_path = sqlite_path.with_name(f"{sqlite_path.name}-shm")
        if wal_path.exists():
            with sqlite3.connect(sqlite_path) as checkpoint_conn:
                checkpoint_conn.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(sqlite_export_path, destination)
        if wal_path.exists():
            shutil.copy2(wal_path, destination.with_name(f"{destination.name}-wal"))
        if shm_path.exists():
            shutil.copy2(shm_path, destination.with_name(f"{destination.name}-shm"))
        exported["db"] = str(destination)

    return exported


def _iter_collect_partition(
    *,
    client: DmfwApiClient,
    keyword: str,
    code: str,
    progress_tracker: DmfwProgressTracker,
    division_repository: SQLiteDivisionRepository,
    partition_threshold: int,
    page_size: int,
    search_type: str,
    match_mode: str,
    started_monotonic: float,
    max_runtime_seconds: int | None,
    division_names: dict[str, str],
    division_children_cache: dict[str, list[DmfwDivision]],
    progress_context: dict[str, object] | None = None,
    stop_event=None,
):
    name = division_names.get(code, code)
    if progress_context is not None:
        progress_context["current_keyword"] = keyword
        progress_context["current_code"] = code
        progress_context["current_name"] = name
        progress_context["current_token"] = f"{keyword}|{code}"
    if progress_tracker.is_completed(keyword, code):
        logger.info(f"区划 {name} ({code}) 字符 '{keyword}' 已在历史进度中完成，跳过")
        return
    _assert_runtime_budget(started_monotonic, max_runtime_seconds)
    _check_stop(stop_event)
    first_page = client.search_places(
        keyword=keyword,
        code=code,
        page=1,
        size=page_size,
        search_type=search_type,
    )
    total = int(first_page.get("total", 0))
    logger.info(f"正在查询字符 '{keyword}'，区划: {name} ({code})，总数: {total}")

    if total > partition_threshold:
        if code in division_children_cache:
            children = division_children_cache[code]
        else:
            children = _get_cached_divisions(
                client=client,
                division_repository=division_repository,
                code=code,
            )
            division_children_cache[code] = children
        if children:
            logger.info(f"区划 {name} ({code}) 的总数 {total} 超过阈值 {partition_threshold}，开始细分下级区划抓取...")
            for child in children:
                division_names[child.code] = child.name
            for child in children:
                _check_stop(stop_event)
                yield from _iter_collect_partition(
                    client=client,
                    keyword=keyword,
                    code=child.code,
                    progress_tracker=progress_tracker,
                    division_repository=division_repository,
                    partition_threshold=partition_threshold,
                    page_size=page_size,
                    search_type=search_type,
                    match_mode=match_mode,
                    started_monotonic=started_monotonic,
                    max_runtime_seconds=max_runtime_seconds,
                    division_names=division_names,
                    division_children_cache=division_children_cache,
                    progress_context=progress_context,
                    stop_event=stop_event,
                )
            progress_tracker.mark_completed(keyword, code)
            if progress_context is not None:
                progress_context["last_completed_keyword"] = keyword
                progress_context["last_completed_code"] = code
                progress_context["last_completed_name"] = name
                progress_context["last_completed_token"] = f"{keyword}|{code}"
            return
        logger.info(f"区划 {name} ({code}) 缺少已缓存的下级区划，保持当前分区直接抓取")

    total_pages = max(1, (total + page_size - 1) // page_size)
    fetched_at_utc = utc_now_iso()
    records = first_page.get("records", [])
    logger.info(f"区划 {name} ({code}) [总数 {total}]: 正在处理第 1/{total_pages} 页，获取到 {len(records)} 个地名")
    yield from _normalize_records(first_page.get("records", []), keyword=keyword, partition_code=code, match_mode=match_mode, fetched_at_utc=fetched_at_utc)

    for page in range(2, total_pages + 1):
        _assert_runtime_budget(started_monotonic, max_runtime_seconds)
        _check_stop(stop_event)
        payload = client.search_places(
            keyword=keyword,
            code=code,
            page=page,
            size=page_size,
            search_type=search_type,
        )
        fetched_at_utc = utc_now_iso()
        page_records = payload.get("records", [])
        logger.info(f"区划 {name} ({code}) [总数 {total}]: 正在处理第 {page}/{total_pages} 页，获取到 {len(page_records)} 个地名")
        yield from _normalize_records(payload.get("records", []), keyword=keyword, partition_code=code, match_mode=match_mode, fetched_at_utc=fetched_at_utc)
    progress_tracker.mark_completed(keyword, code)
    if progress_context is not None:
        progress_context["last_completed_keyword"] = keyword
        progress_context["last_completed_code"] = code
        progress_context["last_completed_name"] = name
        progress_context["last_completed_token"] = f"{keyword}|{code}"


def _get_or_fetch_divisions(
    *,
    client: DmfwApiClient,
    division_repository: SQLiteDivisionRepository,
    code: str,
) -> list[DmfwDivision]:
    cached = division_repository.list_divisions(parent_code=code)
    if cached:
        return cached
    if division_repository.has_division_children_cache(code):
        return []

    divisions = client.list_divisions(code)
    if divisions:
        division_repository.upsert_divisions(divisions)
    division_repository.mark_division_children_fetched(code)
    return divisions


def _get_cached_divisions(
    *,
    client: DmfwApiClient,
    division_repository: SQLiteDivisionRepository,
    code: str,
) -> list[DmfwDivision]:
    _ = client
    return division_repository.list_divisions(parent_code=code)


def _sync_division_subtree(
    *,
    client: DmfwApiClient,
    division_repository: SQLiteDivisionRepository,
    code: str,
    seen_codes: set[str] | None = None,
) -> list[DmfwDivision]:
    seen = seen_codes or set()
    if code in seen:
        return []
    seen.add(code)

    children = _get_or_fetch_divisions(
        client=client,
        division_repository=division_repository,
        code=code,
    )
    collected = list(children)
    for child in children:
        collected.extend(
            _sync_division_subtree(
                client=client,
                division_repository=division_repository,
                code=child.code,
                seen_codes=seen,
            )
        )
    return collected


def _normalize_records(
    records: object,
    *,
    keyword: str,
    partition_code: str,
    match_mode: str,
    fetched_at_utc: str,
) -> list[DmfwPlaceRecord]:
    normalized: list[DmfwPlaceRecord] = []
    if not isinstance(records, list):
        return normalized
    for record in records:
        if isinstance(record, DmfwPlaceRecord):
            normalized.append(record)
            continue
        if isinstance(record, dict):
            normalized.append(
                DmfwPlaceRecord.from_api_record(
                    record,
                    keyword=keyword,
                    partition_code=partition_code,
                    source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
                    match_mode=match_mode,
                    fetched_at_utc=fetched_at_utc,
                )
            )
    return normalized


def _assert_runtime_budget(started_monotonic: float, max_runtime_seconds: int | None) -> None:
    if max_runtime_seconds is None:
        return
    if time.monotonic() - started_monotonic > max_runtime_seconds:
        raise TimeoutError(f"dmfw crawl exceeded max_runtime_seconds={max_runtime_seconds}")


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            candidates = payload["data"]
        elif isinstance(payload.get("data"), dict):
            data = payload["data"]
            if isinstance(data.get("records"), list):
                candidates = data["records"]
            elif isinstance(data.get("rows"), list):
                candidates = data["rows"]
            elif isinstance(data.get("children"), list):
                candidates = data["children"]
        elif isinstance(payload.get("records"), list):
            candidates = payload["records"]
        elif isinstance(payload.get("rows"), list):
            candidates = payload["rows"]
    return [item for item in candidates if isinstance(item, dict)]


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        if isinstance(payload.get("records"), list):
            return [item for item in payload["records"] if isinstance(item, dict)]
        if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("records"), list):
            return [item for item in payload["data"]["records"] if isinstance(item, dict)]
        if isinstance(payload.get("rows"), list):
            return [item for item in payload["rows"] if isinstance(item, dict)]
        if isinstance(payload.get("data"), list):
            return [item for item in payload["data"] if isinstance(item, dict)]
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "records" in payload[0]:
            records = payload[0].get("records", [])
            return [item for item in records if isinstance(item, dict)]
        return [item for item in payload if isinstance(item, dict)]
    return []


def _extract_total(payload: Any, default: int) -> int:
    if isinstance(payload, dict):
        if "total" in payload:
            return int(payload["total"])
        if isinstance(payload.get("data"), dict) and "total" in payload["data"]:
            return int(payload["data"]["total"])
    if isinstance(payload, list) and payload and isinstance(payload[0], dict) and "total" in payload[0]:
        return int(payload[0]["total"])
    return default


def _infer_division_level(code: str) -> str:
    if len(code) <= 2:
        return "province"
    if len(code) <= 4:
        return "city"
    if len(code) <= 6:
        return "district"
    return "town"


def _normalize_formats(formats: list[str]) -> list[str]:
    if not formats or formats == ["all"]:
        return ["json", "csv", "xlsx", "db"]
    normalized: list[str] = []
    for item in formats:
        if item == "all":
            return ["json", "csv", "xlsx", "db"]
        if item not in {"json", "csv", "xlsx", "db"}:
            raise ValueError(f"unsupported export format: {item}")
        normalized.append(item)
    return normalized


def _build_progress_filename(chars: str, match_mode: str, province_codes: list[str] | None) -> str:
    safe_chars = "".join(char for char in chars if char not in {" ", "\n", "\t", ",", "，", "、", ";", "；"})
    if len(safe_chars) > 32:
        import hashlib
        safe_chars = hashlib.md5(safe_chars.encode("utf-8")).hexdigest()
    province_suffix = "all" if not province_codes else "-".join(province_codes)
    return f"dmfw_chars_{safe_chars}_{match_mode}_{province_suffix}.progress.json"


def _build_shared_progress_path(settings: Settings, options: DmfwRunOptions) -> Path:
    match_mode = options.match_mode
    province_suffix = (
        "all" if not options.province_codes
        else "-".join(options.province_codes)
    )
    return (
        settings.raw_dir
        / f"dmfw_chars_shared_{match_mode}_{province_suffix}.progress.json"
    )


def _normalize_chars(raw_chars: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for char in raw_chars:
        if char in {" ", "\n", "\t", ",", "，", "、", ";", "；"}:
            continue
        if char not in seen:
            normalized.append(char)
            seen.add(char)
    return normalized
