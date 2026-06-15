from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from geonode_spider.config.settings import load_settings
from geonode_spider.services.bootstrap import ensure_runtime_directories, export_from_database, run_sample_pipeline
from geonode_spider.services.dmfw import DmfwRunOptions, run_dmfw_chars_pipeline, sync_dmfw_divisions
from geonode_spider.storage.sqlite import SQLiteRegionRepository
from geonode_spider.utils.logging import setup_logging


MATCH_MODE_TO_SEARCH_TYPE = {
    "contain": "模糊",
    "exact": "精确",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="geonode-spider", description="Administrative division spider scaffold.")
    parser.add_argument("--env-file", default=None, help="Path to .env file.")
    parser.add_argument("--config", default=None, help="Path to YAML config file.")
    parser.add_argument("--project-root", default=".", help="Project root for relative path resolution.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize SQLite schema.")
    subparsers.add_parser("show-config", help="Print merged runtime config.")

    sample_parser = subparsers.add_parser("sample-data", help="Persist sample administrative data.")
    sample_parser.add_argument("--source", default="mock")

    export_parser = subparsers.add_parser("export", help="Export data from SQLite.")
    export_parser.add_argument("--format", dest="formats", default="all", help="Comma-separated formats or 'all'.")

    run_parser = subparsers.add_parser("run-pipeline", help="Run the sample pipeline.")
    run_parser.add_argument("--source", default="mock")
    run_parser.add_argument("--export", dest="formats", default="all", help="Comma-separated formats or 'all'.")

    dmfw_parser = subparsers.add_parser("run-dmfw-chars", help="Run dmfw collection for a character set.")
    dmfw_parser.add_argument("--chars", default=None, help="Character set used for searches.")
    dmfw_parser.add_argument("--json", dest="json_path", default=None, help="Path to dmfw task json config.")
    dmfw_parser.add_argument("--export", dest="formats", default=None, help="Comma-separated formats or 'all'.")
    dmfw_parser.add_argument("--resume", action="store_true", help="Resume from the saved dmfw partition progress file.")
    dmfw_parser.add_argument("--match-mode", choices=sorted(MATCH_MODE_TO_SEARCH_TYPE), default=None, help="Search mode: contain/exact.")
    dmfw_parser.add_argument("--province-codes", default=None, help="Comma-separated province codes. Default: all cached provinces.")
    dmfw_parser.add_argument("--flush-batch-size", type=int, default=None, help="Incremental flush size. Default 1000.")
    dmfw_parser.add_argument("--max-runtime-seconds", type=int, default=None, help="Optional runtime cap. Default unlimited.")
    dmfw_parser.add_argument("--sync-divisions-first", action="store_true", help="Refresh province divisions before running.")
    dmfw_parser.add_argument("--no-write-run-db", action="store_true", help="Do not persist this run into the default run database.")
    dmfw_parser.add_argument("--write-total-db", action="store_true", help="Append/upsert records into a cumulative total database.")
    dmfw_parser.add_argument("--total-db-path", default=None, help="Optional custom path for the cumulative total database.")

    subparsers.add_parser("sync-dmfw-divisions", help="Fetch and cache dmfw province divisions into SQLite.")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings(
        env_path=args.env_file,
        yaml_path=args.config,
        project_root=Path(args.project_root),
    )
    setup_logging(settings.log_level)

    if args.command == "show-config":
        print(json.dumps(settings.to_display_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "init-db":
        ensure_runtime_directories(settings)
        repository = SQLiteRegionRepository(settings.sqlite_path)
        repository.initialize()
        print(f"Initialized SQLite database at {settings.sqlite_path}")
        return 0

    if args.command == "sample-data":
        result = run_sample_pipeline(settings=settings, source_name=args.source, export_formats=["all"])
        print(json.dumps({"run_id": result.run_id, "region_count": result.region_count}, ensure_ascii=False))
        return 0

    if args.command == "export":
        exported = export_from_database(settings, _parse_formats(args.formats or "all"))
        print(json.dumps(exported, ensure_ascii=False, indent=2))
        return 0

    if args.command == "run-pipeline":
        result = run_sample_pipeline(
            settings=settings,
            source_name=args.source,
            export_formats=_parse_formats(args.formats),
        )
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "region_count": result.region_count,
                    "source_name": result.source_name,
                    "exported_files": result.exported_files,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "run-dmfw-chars":
        options = _resolve_dmfw_run_options(args)
        result = run_dmfw_chars_pipeline(settings=settings, options=options)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "sync-dmfw-divisions":
        result = sync_dmfw_divisions(settings=settings)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error("unsupported command")
    return 2


def _resolve_dmfw_run_options(args: argparse.Namespace) -> DmfwRunOptions:
    payload = _load_dmfw_task_json(args.json_path)

    chars = args.chars or payload.get("chars")
    if not chars:
        raise SystemExit("run-dmfw-chars requires --chars or a json config containing 'chars'")

    chars_str = str(chars)
    chars_path = Path(chars_str)
    if not chars_path.is_absolute() and args.project_root:
        resolved_path = Path(args.project_root) / chars_path
        if resolved_path.exists() and resolved_path.is_file():
            chars_path = resolved_path
    if chars_path.exists() and chars_path.is_file():
        try:
            import logging
            logging.getLogger(__name__).info(f"Loading character set from file: {chars_path}")
        except Exception:
            pass
        chars_str = chars_path.read_text(encoding="utf-8")

    export_formats = _parse_formats(args.formats) if args.formats else _normalize_export_formats(payload.get("export"))
    province_codes = _normalize_string_list(args.province_codes) if args.province_codes else _normalize_string_list(payload.get("province_codes"))
    match_mode = args.match_mode or str(payload.get("match_mode", "contain"))
    if match_mode not in MATCH_MODE_TO_SEARCH_TYPE:
        raise SystemExit(f"unsupported match_mode: {match_mode}")

    flush_batch_size = args.flush_batch_size if args.flush_batch_size is not None else int(payload.get("flush_batch_size", 1000))
    max_runtime_seconds = args.max_runtime_seconds if args.max_runtime_seconds is not None else _optional_int(payload.get("max_runtime_seconds"))
    resume = bool(args.resume or payload.get("resume", False))
    sync_divisions_first = bool(args.sync_divisions_first or payload.get("sync_divisions_first", False))

    return DmfwRunOptions(
        chars=chars_str,
        export_formats=export_formats,
        resume=resume,
        match_mode=match_mode,
        search_type=MATCH_MODE_TO_SEARCH_TYPE[match_mode],
        province_codes=province_codes,
        flush_batch_size=flush_batch_size,
        max_runtime_seconds=max_runtime_seconds,
        sync_divisions_first=sync_divisions_first,
        json_path=str(args.json_path) if args.json_path else None,
        write_run_db=not bool(args.no_write_run_db or payload.get("no_write_run_db", False)),
        write_total_db=bool(args.write_total_db or payload.get("write_total_db", False)),
        total_db_path=str(args.total_db_path or payload.get("total_db_path")) if (args.total_db_path or payload.get("total_db_path")) else None,
    )


def _load_dmfw_task_json(json_path: str | None) -> dict[str, Any]:
    if not json_path:
        return {}
    path = Path(json_path)
    if not path.exists():
        raise SystemExit(f"dmfw task json not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("dmfw task json must contain a top-level object")
    return payload


def _normalize_export_formats(value: Any) -> list[str]:
    if value in (None, ""):
        return ["db"]
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or ["db"]
    if isinstance(value, str):
        normalized = _parse_formats(value)
        return normalized or ["db"]
    return ["db"]


def _normalize_string_list(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        normalized = [str(item).strip() for item in value if str(item).strip()]
        return normalized or None
    if isinstance(value, str):
        normalized = [item.strip() for item in value.split(",") if item.strip()]
        return normalized or None
    return [str(value).strip()]


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_formats(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]
