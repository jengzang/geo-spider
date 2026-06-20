from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import logging
import shutil
import sqlite3
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from geonode_spider.config.settings import Settings
from geonode_spider.crawler.profile import RequestProfile
from geonode_spider.crawler.proxies import StaticProxyProvider
from geonode_spider.crawler.session import SpiderSession
from geonode_spider.exporters.csv_exporter import CsvExporter
from geonode_spider.exporters.excel_exporter import ExcelExporter
from geonode_spider.exporters.json_exporter import JsonExporter
from geonode_spider.models.place import DmfwDivision, DmfwPlaceRecord
from geonode_spider.models.region import CrawlRunRecord, utc_now_iso
from geonode_spider.storage.sqlite import SQLiteDivisionRepository, SQLitePlaceRepository, SQLiteTotalPlaceRepository


MAX_PARALLEL_DMFW_WORKERS = 4


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
        self._write_threshold = 1000 if len(self.chars) > 100 else 1
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

    def save(self) -> None:
        if self._dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            self._dirty = False
            self._pending_count = 0


def sync_dmfw_divisions(*, settings: Settings) -> dict[str, object]:
    repository = SQLiteDivisionRepository(settings.sqlite_path)
    repository.initialize()
    client = _build_dmfw_api_client(settings)
    divisions = client.list_divisions("0")
    repository.upsert_divisions(divisions)
    return {
        "source_name": "dmfw",
        "division_count": len(divisions),
        "codes": [division.code for division in divisions],
    }


def run_dmfw_chars_pipeline(*, settings: Settings, options: DmfwRunOptions) -> dict[str, object]:
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
    province_divisions = division_repository.list_divisions(parent_code="0")
    if not province_divisions:
        province_divisions = client.list_divisions("0")
        division_repository.upsert_divisions(province_divisions)
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

    unique_count = len(_normalize_chars(options.chars))
    display_chars = options.chars.replace("\n", " ").replace("\r", " ")
    display_chars = display_chars[:50] + "..." if len(display_chars) > 50 else display_chars
    crawl_scope = "指定省份" if options.province_codes else "全国优先"
    logger.info(
        f"开始抓取地名任务，匹配模式: {options.match_mode}，抓取范围: {crawl_scope}，"
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

    requested_formats = _normalize_formats(options.export_formats or ["db"])
    db_only_export = set(requested_formats) == {"db"}
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    started_at = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    flush_count = 0
    persisted_total = 0
    fetched_total = 0
    deduped: dict[str, DmfwPlaceRecord] = {}
    division_children_cache: dict[str, list[DmfwDivision]] = {}
    if not options.province_codes:
        division_children_cache[""] = province_divisions
    for division in province_divisions:
        cached_children = division_repository.list_divisions(parent_code=division.code)
        if cached_children:
            division_children_cache[division.code] = cached_children

    try:
        for char in _normalize_chars(options.chars):
            initial_divisions = province_divisions if options.province_codes else [
                DmfwDivision(code="", name="全国", parent_code="", level="country")
            ]
            for division in initial_divisions:
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
                ):
                    deduped[place.source_id] = place
                    fetched_total += 1
                    if len(deduped) >= options.flush_batch_size:
                        batch = list(deduped.values())
                        if options.write_run_db:
                            repository.upsert_places(batch)
                        if total_repository is not None:
                            total_repository.upsert_places(batch)
                        flush_count += 1
                        logger.info(
                            f"已批量写入 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                            f"累计写入批次数: {flush_count}"
                        )
                        deduped.clear()
        if deduped:
            batch = list(deduped.values())
            if options.write_run_db:
                repository.upsert_places(batch)
            if total_repository is not None:
                total_repository.upsert_places(batch)
            flush_count += 1
            logger.info(
                f"已批量写入最后一批 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                f"累计写入批次数: {flush_count}"
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
        # Flush any remaining buffered progress to disk
        progress.save()
        logger.info(
            f"抓取任务顺利完成。累计抓取地名数: {fetched_total}，"
            f"数据库已保存总数: {persisted_total}，累计写入批次数: {flush_count}"
        )
    except BaseException as exc:
        try:
            progress.save()
        except Exception:
            pass
        if deduped:
            batch = list(deduped.values())
            if options.write_run_db:
                repository.upsert_places(batch)
            if total_repository is not None:
                total_repository.upsert_places(batch)
            flush_count += 1
            logger.info(
                f"异常退出前：已批量写入最后一批 {len(batch)} 个地名至数据库。当前此运行累计获取 {fetched_total} 个地名，"
                f"累计写入批次数: {flush_count}"
            )
            deduped.clear()
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
        logger.error(f"抓取任务遇到异常中断: {exc}", exc_info=True)
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
        "write_run_db": options.write_run_db,
        "write_total_db": options.write_total_db,
        "total_db_path": str(total_db_path) if total_db_path is not None else None,
    }


def run_dmfw_parallel_tasks(*, settings: Settings, task_options: list[DmfwRunOptions], workers: int) -> dict[str, object]:
    if len(task_options) < 2:
        raise ValueError("parallel dmfw mode requires at least two task options")

    export_formats = _validate_parallel_task_options(settings, task_options)
    _prime_parallel_division_children(settings, task_options)

    total_db_path = _resolve_total_db_path(settings, task_options[0])
    SQLiteTotalPlaceRepository(total_db_path).initialize()

    effective_workers = min(max(1, workers), len(task_options), MAX_PARALLEL_DMFW_WORKERS)
    future_map: dict[object, DmfwRunOptions] = {}
    results: list[dict[str, object]] = []

    with ProcessPoolExecutor(max_workers=effective_workers) as executor:
        for option in task_options:
            future = executor.submit(
                _run_dmfw_parallel_task_worker,
                settings,
                option,
                _build_task_namespace(option),
            )
            future_map[future] = option
        for future in as_completed(list(future_map)):
            results.append(future.result())

    total_repository = SQLiteTotalPlaceRepository(total_db_path)
    total_repository.initialize()
    persisted_total = total_repository.count_places()
    db_only_export = set(export_formats) == {"db"}
    stored_places = [] if db_only_export else total_repository.list_places()
    exported = export_dmfw_places(
        records=stored_places,
        export_dir=settings.export_dir,
        sqlite_path=total_db_path,
        formats=export_formats,
    )

    return {
        "mode": "parallel",
        "task_count": len(task_options),
        "workers": effective_workers,
        "max_supported_workers": MAX_PARALLEL_DMFW_WORKERS,
        "place_count": persisted_total if db_only_export else len(stored_places),
        "persisted_count": persisted_total,
        "total_db_path": str(total_db_path),
        "exported_files": exported,
        "tasks": sorted(results, key=lambda item: str(item.get("task_json") or "")),
    }


def _run_dmfw_parallel_task_worker(settings: Settings, options: DmfwRunOptions, task_namespace: str) -> dict[str, object]:
    worker_settings = replace(settings, raw_dir=settings.raw_dir / task_namespace)
    worker_options = replace(
        options,
        write_run_db=False,
        skip_export=True,
        sync_divisions_first=False,
    )
    return run_dmfw_chars_pipeline(settings=worker_settings, options=worker_options)


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


def _prime_parallel_division_children(settings: Settings, task_options: list[DmfwRunOptions]) -> None:
    repository = SQLiteDivisionRepository(settings.sqlite_path)
    repository.initialize()
    root_divisions = repository.list_divisions(parent_code="0")
    if not root_divisions:
        return

    requested_codes = {
        code
        for option in task_options
        for code in (option.province_codes or [])
    }
    target_codes = requested_codes or {division.code for division in root_divisions}
    missing_codes = [
        code
        for code in sorted(target_codes)
        if not repository.list_divisions(parent_code=code)
    ]
    if not missing_codes:
        return

    client = _build_dmfw_api_client(settings)
    for code in missing_codes:
        children = client.list_divisions(code)
        if children:
            repository.upsert_divisions(children)


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
):
    name = division_names.get(code, code)
    if progress_tracker.is_completed(keyword, code):
        logger.info(f"区划 {name} ({code}) 字符 '{keyword}' 已在历史进度中完成，跳过")
        return
    _assert_runtime_budget(started_monotonic, max_runtime_seconds)
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
            children = division_repository.list_divisions(parent_code=code)
            if not children:
                children = client.list_divisions(code)
                if children:
                    division_repository.upsert_divisions(children)
            division_children_cache[code] = children
        if children:
            logger.info(f"区划 {name} ({code}) 的总数 {total} 超过阈值 {partition_threshold}，开始细分下级区划抓取...")
            for child in children:
                division_names[child.code] = child.name
            for child in children:
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
                )
            progress_tracker.mark_completed(keyword, code)
            return

    total_pages = max(1, (total + page_size - 1) // page_size)
    fetched_at_utc = utc_now_iso()
    records = first_page.get("records", [])
    logger.info(f"区划 {name} ({code}) [总数 {total}]: 正在处理第 1/{total_pages} 页，获取到 {len(records)} 个地名")
    yield from _normalize_records(first_page.get("records", []), keyword=keyword, partition_code=code, match_mode=match_mode, fetched_at_utc=fetched_at_utc)

    for page in range(2, total_pages + 1):
        _assert_runtime_budget(started_monotonic, max_runtime_seconds)
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
