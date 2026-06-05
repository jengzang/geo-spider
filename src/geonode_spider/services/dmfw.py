from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

    def __post_init__(self) -> None:
        if self.resume and self.path.exists():
            self._state = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._state = {"chars": self.chars, "completed": []}
            self._save()

    def is_completed(self, keyword: str, code: str) -> bool:
        return f"{keyword}|{code}" in set(self._state["completed"])

    def mark_completed(self, keyword: str, code: str) -> None:
        token = f"{keyword}|{code}"
        if token not in self._state["completed"]:
            self._state["completed"].append(token)
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")


def sync_dmfw_divisions(*, settings: Settings) -> dict[str, object]:
    repository = SQLiteDivisionRepository(settings.sqlite_path)
    repository.initialize()

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
    client = DmfwApiClient(
        settings.dmfw_base_url,
        session=session,
        bypass_env_proxy=settings.dmfw_bypass_env_proxy,
    )
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
    client = DmfwApiClient(
        settings.dmfw_base_url,
        session=session,
        bypass_env_proxy=settings.dmfw_bypass_env_proxy,
    )
    province_divisions = division_repository.list_divisions(parent_code="0")
    if not province_divisions:
        province_divisions = client.list_divisions("0")
        division_repository.upsert_divisions(province_divisions)
    if options.province_codes:
        allowed = set(options.province_codes)
        province_divisions = [division for division in province_divisions if division.code in allowed]

    progress = DmfwProgressTracker(
        path=settings.raw_dir / _build_progress_filename(options.chars, options.match_mode, options.province_codes),
        chars=options.chars,
        resume=options.resume,
    )

    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    started_at = datetime.now(UTC).isoformat()
    started_monotonic = time.monotonic()
    flush_count = 0
    persisted_total = 0
    deduped: dict[str, DmfwPlaceRecord] = {}

    try:
        for char in _normalize_chars(options.chars):
            for division in province_divisions:
                for place in _iter_collect_partition(
                    client=client,
                    keyword=char,
                    code=division.code,
                    progress_tracker=progress,
                    partition_threshold=settings.dmfw_partition_threshold,
                    page_size=settings.dmfw_page_size,
                    search_type=options.search_type,
                    match_mode=options.match_mode,
                    started_monotonic=started_monotonic,
                    max_runtime_seconds=options.max_runtime_seconds,
                ):
                    deduped[place.source_id] = place
                    if len(deduped) >= options.flush_batch_size:
                        batch = list(deduped.values())
                        if options.write_run_db:
                            repository.upsert_places(batch)
                            persisted_total = repository.count_places()
                        if total_repository is not None:
                            total_repository.upsert_places(batch)
                        flush_count += 1
                        deduped.clear()
        if deduped:
            batch = list(deduped.values())
            if options.write_run_db:
                repository.upsert_places(batch)
                persisted_total = repository.count_places()
            if total_repository is not None:
                total_repository.upsert_places(batch)
            flush_count += 1
            deduped.clear()
        if options.write_run_db:
            stored_places = repository.list_places()
        elif total_repository is not None:
            stored_places = total_repository.list_places()
            persisted_total = total_repository.count_places()
        else:
            stored_places = []
        exported = export_dmfw_places(
            records=stored_places,
            export_dir=settings.export_dir,
            sqlite_path=settings.sqlite_path if options.write_run_db else (total_db_path or settings.sqlite_path),
            formats=options.export_formats or ["db"],
        )
        finished_at = datetime.now(UTC).isoformat()
        repository.record_crawl_run(
            CrawlRunRecord(
                run_id=run_id,
                source_name="dmfw",
                status="success",
                item_count=len(stored_places),
                started_at=started_at,
                finished_at=finished_at,
            )
        )
    except Exception as exc:
        if deduped:
            batch = list(deduped.values())
            if options.write_run_db:
                repository.upsert_places(batch)
                persisted_total = repository.count_places()
            if total_repository is not None:
                total_repository.upsert_places(batch)
            flush_count += 1
            deduped.clear()
        finished_at = datetime.now(UTC).isoformat()
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
        raise

    return {
        "run_id": run_id,
        "place_count": len(stored_places),
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
        shutil.copy2(sqlite_path, destination)
        exported["db"] = str(destination)

    return exported


def _iter_collect_partition(
    *,
    client: DmfwApiClient,
    keyword: str,
    code: str,
    progress_tracker: DmfwProgressTracker,
    partition_threshold: int,
    page_size: int,
    search_type: str,
    match_mode: str,
    started_monotonic: float,
    max_runtime_seconds: int | None,
):
    if progress_tracker.is_completed(keyword, code):
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
    if total > partition_threshold:
        children = client.list_divisions(code)
        if children:
            for child in children:
                yield from _iter_collect_partition(
                    client=client,
                    keyword=keyword,
                    code=child.code,
                    progress_tracker=progress_tracker,
                    partition_threshold=partition_threshold,
                    page_size=page_size,
                    search_type=search_type,
                    match_mode=match_mode,
                    started_monotonic=started_monotonic,
                    max_runtime_seconds=max_runtime_seconds,
                )
            progress_tracker.mark_completed(keyword, code)
            return
    fetched_at_utc = utc_now_iso()
    yield from _normalize_records(first_page.get("records", []), keyword=keyword, partition_code=code, match_mode=match_mode, fetched_at_utc=fetched_at_utc)
    total_pages = max(1, (total + page_size - 1) // page_size)
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
    safe_chars = "".join(char for char in chars if char not in {" ", "\n", "\t"})
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
