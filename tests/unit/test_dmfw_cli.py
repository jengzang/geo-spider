from __future__ import annotations

import json
from pathlib import Path

from geonode_spider.cli import main


def test_cli_runs_dmfw_chars_pipeline(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_dmfw_chars_pipeline(*, settings, chars, export_formats, resume):
        captured["chars"] = chars
        captured["export_formats"] = export_formats
        captured["resume"] = resume
        captured["sqlite_path"] = settings.sqlite_path
        return {
            "run_id": "run-1",
            "place_count": 3,
            "source_name": "dmfw",
            "exported_files": {"json": str(tmp_path / "exports" / "dmfw_places.json")},
        }

    monkeypatch.setattr("geonode_spider.cli.run_dmfw_chars_pipeline", fake_run_dmfw_chars_pipeline)

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "run-dmfw-chars",
            "--chars",
            "尾村",
            "--export",
            "json,csv",
            "--resume",
        ]
    )

    assert exit_code == 0
    assert captured["chars"] == "尾村"
    assert captured["export_formats"] == ["json", "csv"]
    assert captured["resume"] is True
    assert captured["sqlite_path"] == tmp_path / "data/processed/geonode_spider.db"
