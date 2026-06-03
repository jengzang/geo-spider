from __future__ import annotations

import json
import shutil
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
from geonode_spider.models.region import CrawlRunRecord
from geonode_spider.sources.dmfw import DmfwCollector
from geonode_spider.storage.sqlite import SQLitePlaceRepository


class DmfwApiClient:
    def __init__(self, base_url: str, session: SpiderSession) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = session

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
        search_type: str = "模糊匹配",
    ) -> dict[str, object]:
        response = self.session.post(
            f"{self.base_url}/stname/listPub",
            data={
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


def run_dmfw_chars_pipeline(
    *,
    settings: Settings,
    chars: str,
    export_formats: list[str] | None = None,
    resume: bool = False,
) -> dict[str, object]:
    repository = SQLitePlaceRepository(settings.sqlite_path)
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
    client = DmfwApiClient(settings.dmfw_base_url, session=session)
    collector = DmfwCollector(
        client=client,
        partition_threshold=settings.dmfw_partition_threshold,
        page_size=settings.dmfw_page_size,
        search_type=settings.dmfw_search_type,
    )
    progress = DmfwProgressTracker(
        path=settings.raw_dir / _build_progress_filename(chars),
        chars=chars,
        resume=resume,
    )

    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    started_at = datetime.now(UTC).isoformat()
    try:
        places = collector.collect_for_chars(chars, progress_tracker=progress)
        repository.upsert_places(places)
        stored_places = repository.list_places()
        exported = export_dmfw_places(
            records=stored_places,
            export_dir=settings.export_dir,
            sqlite_path=settings.sqlite_path,
            formats=export_formats or ["all"],
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
        "source_name": "dmfw",
        "exported_files": exported,
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


def _build_progress_filename(chars: str) -> str:
    safe_chars = "".join(char for char in chars if char not in {" ", "\n", "\t"})
    return f"dmfw_chars_{safe_chars}.progress.json"
