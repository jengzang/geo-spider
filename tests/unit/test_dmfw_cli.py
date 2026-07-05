from __future__ import annotations

import json
from pathlib import Path

from dmfw_places_spider.cli import main


def test_cli_runs_dmfw_chars_pipeline(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_dmfw_chars_pipeline(*, settings, options):
        captured["chars"] = options.chars
        captured["export_formats"] = options.export_formats
        captured["resume"] = options.resume
        captured["sqlite_path"] = settings.sqlite_path
        captured["match_mode"] = options.match_mode
        captured["province_codes"] = options.province_codes
        captured["flush_batch_size"] = options.flush_batch_size
        captured["write_run_db"] = options.write_run_db
        captured["write_total_db"] = options.write_total_db
        captured["total_db_path"] = options.total_db_path
        return {
            "run_id": "run-1",
            "place_count": 3,
            "source_name": "dmfw",
            "exported_files": {"json": str(tmp_path / "exports" / "dmfw_places.json")},
        }

    monkeypatch.setattr("dmfw_places_spider.cli.run_dmfw_chars_pipeline", fake_run_dmfw_chars_pipeline)

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
            "--match-mode",
            "contain",
            "--province-codes",
            "35,44",
            "--flush-batch-size",
            "500",
            "--write-total-db",
            "--total-db-path",
            str(tmp_path / "data/processed/dmfw_total.db"),
        ]
    )

    assert exit_code == 0
    assert captured["chars"] == "尾村"
    assert captured["export_formats"] == ["json", "csv"]
    assert captured["resume"] is True
    assert captured["sqlite_path"] == tmp_path / "data/processed/dmfw_places_spider.db"
    assert captured["match_mode"] == "contain"
    assert captured["province_codes"] == ["35", "44"]
    assert captured["flush_batch_size"] == 500
    assert captured["write_run_db"] is True
    assert captured["write_total_db"] is True
    assert captured["total_db_path"] == str(tmp_path / "data/processed/dmfw_total.db")


def test_cli_dmfw_default_export_is_db_only(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_run_dmfw_chars_pipeline(*, settings, options):
        captured["export_formats"] = options.export_formats
        return {"run_id": "run-default-export", "place_count": 0, "source_name": "dmfw", "exported_files": {}}

    monkeypatch.setattr("dmfw_places_spider.cli.run_dmfw_chars_pipeline", fake_run_dmfw_chars_pipeline)

    exit_code = main([
        "--project-root",
        str(tmp_path),
        "run-dmfw-chars",
        "--chars",
        "村",
    ])

    assert exit_code == 0
    assert captured["export_formats"] == ["db"]


def test_cli_runs_dmfw_chars_pipeline_from_json(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    task_path = tmp_path / "dmfw-task.json"
    task_path.write_text(
        json.dumps(
            {
                "chars": "村",
                "match_mode": "exact",
                "province_codes": ["44", "50"],
                "resume": True,
                "export": ["json"],
                "flush_batch_size": 1200,
                "max_runtime_seconds": 180,
                "sync_divisions_first": True,
                "no_write_run_db": True,
                "write_total_db": True,
                "total_db_path": str(tmp_path / "data/processed/dmfw_total_json.db"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_run_dmfw_chars_pipeline(*, settings, options):
        captured["chars"] = options.chars
        captured["match_mode"] = options.match_mode
        captured["province_codes"] = options.province_codes
        captured["resume"] = options.resume
        captured["export_formats"] = options.export_formats
        captured["flush_batch_size"] = options.flush_batch_size
        captured["max_runtime_seconds"] = options.max_runtime_seconds
        captured["sync_divisions_first"] = options.sync_divisions_first
        captured["json_path"] = options.json_path
        captured["write_run_db"] = options.write_run_db
        captured["write_total_db"] = options.write_total_db
        captured["total_db_path"] = options.total_db_path
        return {"run_id": "run-2", "place_count": 0, "source_name": "dmfw", "exported_files": {}}

    monkeypatch.setattr("dmfw_places_spider.cli.run_dmfw_chars_pipeline", fake_run_dmfw_chars_pipeline)

    exit_code = main([
        "--project-root",
        str(tmp_path),
        "run-dmfw-chars",
        "--json",
        str(task_path),
    ])

    assert exit_code == 0
    assert captured["chars"] == "村"
    assert captured["match_mode"] == "exact"
    assert captured["province_codes"] == ["44", "50"]
    assert captured["resume"] is True
    assert captured["export_formats"] == ["json"]
    assert captured["flush_batch_size"] == 1200
    assert captured["max_runtime_seconds"] == 180
    assert captured["sync_divisions_first"] is True
    assert captured["json_path"] == str(task_path)
    assert captured["write_run_db"] is False
    assert captured["write_total_db"] is True
    assert captured["total_db_path"] == str(tmp_path / "data/processed/dmfw_total_json.db")


def test_cli_runs_sync_dmfw_divisions(monkeypatch, tmp_path: Path, capsys) -> None:
    def fake_sync_dmfw_divisions(*, settings):
        assert settings.sqlite_path == tmp_path / "data/processed/dmfw_places_spider.db"
        return {"source_name": "dmfw", "division_count": 34, "codes": ["11", "12"]}

    monkeypatch.setattr("dmfw_places_spider.cli.sync_dmfw_divisions", fake_sync_dmfw_divisions)

    exit_code = main([
        "--project-root",
        str(tmp_path),
        "sync-dmfw-divisions",
    ])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["division_count"] == 34
    assert payload["codes"] == ["11", "12"]


def test_cli_settings_default_dmfw_bypass_env_proxy(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.yaml").write_text("{}\n", encoding="utf-8")

    from dmfw_places_spider.config.settings import load_settings

    settings = load_settings(project_root=tmp_path)

    assert settings.dmfw_bypass_env_proxy is True


def test_cli_settings_default_sqlite_stores_dmfw_divisions(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.yaml").write_text("{}\n", encoding="utf-8")

    from dmfw_places_spider.config.settings import load_settings
    from dmfw_places_spider.storage.sqlite import SQLiteDivisionRepository

    settings = load_settings(project_root=tmp_path)
    repository = SQLiteDivisionRepository(settings.sqlite_path)
    repository.initialize()

    assert repository.list_divisions(parent_code="0") == []
