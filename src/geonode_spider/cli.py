from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from geonode_spider.config.settings import load_settings
from geonode_spider.services.bootstrap import ensure_runtime_directories, export_from_database, run_sample_pipeline
from geonode_spider.services.dmfw import run_dmfw_chars_pipeline
from geonode_spider.storage.sqlite import SQLiteRegionRepository
from geonode_spider.utils.logging import setup_logging


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

    dmfw_parser = subparsers.add_parser("run-dmfw-chars", help="Run contain-based dmfw collection for a character set.")
    dmfw_parser.add_argument("--chars", required=True, help="Character set used for contain-based searches.")
    dmfw_parser.add_argument("--export", dest="formats", default="all", help="Comma-separated formats or 'all'.")
    dmfw_parser.add_argument("--resume", action="store_true", help="Resume from the saved dmfw partition progress file.")

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
        exported = export_from_database(settings, _parse_formats(args.formats))
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
        result = run_dmfw_chars_pipeline(
            settings=settings,
            chars=args.chars,
            export_formats=_parse_formats(args.formats),
            resume=bool(args.resume),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.error("unsupported command")
    return 2


def _parse_formats(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]
