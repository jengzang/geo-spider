"""同步 ID 池命令 —— 从 txt 文件导入 id_tasks。"""

from __future__ import annotations

import argparse
import logging
import os
import time

from dmfw_details_spider.cli import add_common_args, add_id_file_args
from dmfw_details_spider.id_pool import iter_ids_from_files, count_lines_in_file
from dmfw_details_spider.state_db import StateDB

logger = logging.getLogger(__name__)


def sync(config: object) -> dict:
    """执行同步，返回统计字典。"""
    state_db = StateDB(config.state_db)  # type: ignore[attr-defined]
    state_db.initialize()

    id_files = getattr(config, "id_files", []) or []
    if not id_files:
        id_files_raw = os.environ.get("DMFW_ID_FILES", "")
        id_files = [p.strip() for p in id_files_raw.split(",") if p.strip()]

    if not id_files and getattr(config, "id_file", None):
        id_files = [getattr(config, "id_file", "")]

    if not id_files:
        logger.error("请指定 --id-file")
        return {"error": "未指定 ID 文件"}

    total_in_files = 0
    for fp in id_files:
        n = count_lines_in_file(fp)
        logger.info(f"ID 文件: {fp} ({n} 行)")
        total_in_files += n

    start = time.monotonic()
    result = state_db.sync_ids(iter_ids_from_files(id_files))
    elapsed = time.monotonic() - start

    stats = state_db.get_stats()

    print()
    print("=" * 50)
    print("ID 同步完成")
    print("=" * 50)
    print(f"ID 文件总数: {total_in_files:,}")
    print(f"新增 ID 数: {result['added']:,}")
    print(f"已存在 ID 数: {result['existed']:,}")
    print(f"进度库总任务数: {stats.get('total', 0):,}")
    print(f"  done:    {stats.get('done', 0):,}")
    print(f"  pending: {stats.get('pending', 0):,}")
    print(f"  claimed: {stats.get('claimed', 0):,}")
    print(f"  retry:   {stats.get('retry', 0):,}")
    print(f"  failed:  {stats.get('failed', 0):,}")
    print(f"耗时: {elapsed:.1f}s")
    print("=" * 50)
    return {**result, **stats}


def main() -> None:
    parser = argparse.ArgumentParser(description="同步 ID 池到进度库")
    add_common_args(parser)
    add_id_file_args(parser)

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    sync(args)


if __name__ == "__main__":
    main()
