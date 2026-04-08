from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from geonode_spider.config.settings import Settings
from geonode_spider.services.bootstrap import ensure_runtime_directories, run_sample_pipeline


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
