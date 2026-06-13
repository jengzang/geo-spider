from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from geonode_spider.config.settings import Settings
from geonode_spider.services.bootstrap import ensure_runtime_directories, run_sample_pipeline
from geonode_spider.services.dmfw import DmfwRunOptions, run_dmfw_chars_pipeline
from geonode_spider.storage.sqlite import SQLitePlaceRepository


class _FakeDmfwClient:
    def __init__(self) -> None:
        self.search_calls: list[tuple[str, str, int]] = []
        self.list_division_calls: list[str] = []

    def list_divisions(self, code: str):
        self.list_division_calls.append(code)
        return []

    def search_places(self, *, keyword: str, code: str, page: int = 1, size: int = 100, place_type_code: str = "", year: int = 0, search_type: str = "模糊"):
        _ = (size, place_type_code, year, search_type)
        self.search_calls.append((keyword, code, page))
        return {
            "total": 1,
            "records": [
                {
                    "id": f"{keyword}-{code}-1",
                    "place_code": f"{code}001",
                    "standard_name": f"{keyword}地名",
                    "place_type": "行政村",
                    "place_type_code": "21610",
                    "province_name": "测试省",
                    "city_name": "测试市",
                    "area_name": "测试区",
                    "area": code,
                    "gdm": {"type": "multipoint", "coordinates": [[118.1, 24.1]]},
                }
            ],
        }


def test_sample_pipeline_persists_and_exports_all_formats(tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        log_level="INFO",
        sqlite_path=tmp_path / "processed" / "geonode_spider.db",
        export_dir=tmp_path / "exports",
        raw_dir=tmp_path / "raw",
        interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed",
        request_timeout=10,
        request_retries=2,
        sleep_min_seconds=0.0,
        sleep_max_seconds=0.0,
        backoff_base_seconds=0.1,
        proxy_enabled=False,
        proxy_pool=[],
        geo_provider="mock",
        geo_api_key="",
        geo_endpoint="",
    )
    ensure_runtime_directories(settings)

    result = run_sample_pipeline(settings=settings, source_name="mock", export_formats=["json", "csv", "xlsx", "db"])

    assert result.region_count >= 4
    assert (settings.export_dir / "regions.json").exists()
    assert (settings.export_dir / "regions.csv").exists()
    assert (settings.export_dir / "regions.xlsx").exists()
    assert (settings.export_dir / "regions.db").exists()

    exported_json = json.loads((settings.export_dir / "regions.json").read_text(encoding="utf-8"))
    assert exported_json[0]["code"] == "110000"

    with sqlite3.connect(settings.export_dir / "regions.db") as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
    assert row_count == result.region_count


def test_dmfw_db_only_export_skips_full_list_but_preserves_counts(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        env="test",
        log_level="INFO",
        sqlite_path=tmp_path / "processed" / "geonode_spider.db",
        export_dir=tmp_path / "exports",
        raw_dir=tmp_path / "raw",
        interim_dir=tmp_path / "interim",
        processed_dir=tmp_path / "processed",
        request_timeout=10,
        request_retries=1,
        sleep_min_seconds=0.0,
        sleep_max_seconds=0.0,
        backoff_base_seconds=0.0,
        proxy_enabled=False,
        proxy_pool=[],
        geo_provider="mock",
        geo_api_key="",
        geo_endpoint="",
        dmfw_page_size=100,
        dmfw_partition_threshold=3000,
        dmfw_search_type="模糊",
    )
    ensure_runtime_directories(settings)

    fake_client = _FakeDmfwClient()
    monkeypatch.setattr("geonode_spider.services.dmfw.DmfwApiClient", lambda *args, **kwargs: fake_client)

    from geonode_spider.models.place import DmfwDivision
    division_repository = SQLitePlaceRepository(settings.sqlite_path)
    division_repository.initialize()
    from geonode_spider.storage.sqlite import SQLiteDivisionRepository
    root_repository = SQLiteDivisionRepository(settings.sqlite_path)
    root_repository.initialize()
    root_repository.upsert_divisions([DmfwDivision(code="35", name="福建省", parent_code="0", level="province")])

    original_list_places = SQLitePlaceRepository.list_places

    def fail_list_places(self):
        raise AssertionError("db-only export should not call list_places")

    monkeypatch.setattr(SQLitePlaceRepository, "list_places", fail_list_places)

    result = run_dmfw_chars_pipeline(
        settings=settings,
        options=DmfwRunOptions(chars="村", export_formats=["db"], flush_batch_size=1),
    )

    monkeypatch.setattr(SQLitePlaceRepository, "list_places", original_list_places)

    assert result["place_count"] == 1
    assert result["persisted_count"] == 1
    assert Path(result["exported_files"]["db"]).exists()

    with sqlite3.connect(settings.export_dir / "dmfw_places.db") as conn:
        row_count = conn.execute("SELECT COUNT(*) FROM dmfw_places").fetchone()[0]
    assert row_count == 1
