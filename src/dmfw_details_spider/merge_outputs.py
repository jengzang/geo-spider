"""worker 临时库汇总到总库。"""

from __future__ import annotations

import argparse
import logging
import os

from dmfw_details_spider.cli import add_common_args, add_merge_args
from dmfw_details_spider.config import DEFAULTS
from dmfw_details_spider.output_db import MasterDB, merge_run_directory

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="汇总 worker 临时库到总库")
    add_common_args(parser)
    add_merge_args(parser)
    parser.add_argument(
        "--run-id",
        help="run_id (默认从路径名提取)",
    )

    args = parser.parse_args()
    import logging as _logging
    _logging.basicConfig(
        level=getattr(_logging, args.log_level.upper(), _logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    worker_output_dir = args.worker_output_dir
    if not os.path.isdir(worker_output_dir):
        logger.error(f"worker 输出目录不存在: {worker_output_dir}")
        raise SystemExit(1)

    run_id = args.run_id or os.path.basename(worker_output_dir.rstrip("/"))

    master = MasterDB(args.master_db)
    master.initialize()

    logger.info(f"汇总目录: {worker_output_dir}")
    logger.info(f"总库: {args.master_db}")
    logger.info(f"run_id: {run_id}")

    result = merge_run_directory(
        worker_output_dir, master, run_id,
        delete_after=args.delete_worker_db_after_merge,
    )

    print()
    print("=" * 50)
    print("汇总完成")
    print("=" * 50)
    print(f"扫描 worker 库数量: {result['scanned']}")
    print(f"读取记录数: {result['total_read']:,}")
    print(f"新增记录数: ~{result['total_inserted']:,}")
    print(f"更新记录数: ~{result['total_updated']:,}")
    print(f"异常记录数: {result['total_errors']}")
    print(f"总库当前记录数: {master.count():,}")
    print("=" * 50)


if __name__ == "__main__":
    main()
