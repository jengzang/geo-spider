from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Sequence

from xzqh_spider.crawler import crawl
from xzqh_spider.repository import XzqhRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xzqh-spider",
        description="行政区划代码爬虫 — tool.51yww.com",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Run the crawl")
    crawl_parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (default: 0.5)")
    crawl_parser.add_argument("--output", default="data/processed/xzqh.db", help="SQLite output path")
    crawl_parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    crawl_parser.add_argument("--checkpoint", default=None, help="Checkpoint file path")
    crawl_parser.add_argument("--sample-limit", type=int, default=0, help="Limit pages fetched (0=unlimited)")
    crawl_parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    export_parser = subparsers.add_parser("export", help="Export from SQLite")
    export_parser.add_argument("--input", default="data/processed/xzqh.db", help="SQLite input path")
    export_parser.add_argument("--format", dest="fmt", default="json", choices=["json", "csv", "db"])
    export_parser.add_argument("--output", default=None, help="Export file path (auto-generated if omitted)")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level) if hasattr(args, "log_level") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "crawl":
        result = crawl(
            db_path=args.output,
            delay=args.delay,
            resume=args.resume,
            checkpoint_path=args.checkpoint,
            sample_limit=args.sample_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "export":
        return _do_export(args)

    parser.error("unsupported command")
    return 2


def _do_export(args: argparse.Namespace) -> int:
    import csv
    import shutil
    import sqlite3

    repo = XzqhRepository(args.input)
    divisions = repo.list_all()
    if not divisions:
        print("No data to export.", file=sys.stderr)
        return 1

    fmt: str = args.fmt
    output = args.output

    if fmt == "json":
        output = output or "data/exports/xzqh_divisions.json"
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        data = [d.to_dict() for d in divisions]
        Path(output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Exported {len(divisions)} divisions to {output}")

    elif fmt == "csv":
        output = output or "data/exports/xzqh_divisions.csv"
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "code", "name", "short_code", "parent_code", "level",
                "level_text", "full_name", "status", "source_url", "captured_at",
            ])
            writer.writeheader()
            for d in divisions:
                writer.writerow(d.to_dict())
        print(f"Exported {len(divisions)} divisions to {output}")

    elif fmt == "db":
        output = output or "data/exports/xzqh_divisions.db"
        dest = Path(output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = Path(args.input)
        # Checkpoint WAL before copy
        with sqlite3.connect(str(src)) as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        if dest.exists():
            dest.unlink()
        shutil.copy2(src, dest)
        print(f"Exported database to {output}")

    return 0
