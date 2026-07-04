"""进度查看命令。"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from dmfw_details_spider.cli import add_common_args
from dmfw_details_spider.config import DEFAULTS
from dmfw_details_spider.output_db import MasterDB
from dmfw_details_spider.state_db import StateDB

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="查看采集进度")
    add_common_args(parser)
    parser.add_argument(
        "--master-db",
        default=DEFAULTS["master_db"],
        help=f"总库路径 (默认: {DEFAULTS['master_db']})",
    )

    args = parser.parse_args()
    import logging as _logging
    _logging.basicConfig(
        level=getattr(_logging, args.log_level.upper(), _logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    state = StateDB(args.state_db)
    stats = state.get_stats()

    total = stats.get("total", 0)
    done = stats.get("done", 0)
    pending = stats.get("pending", 0)
    claimed = stats.get("claimed", 0)
    retry = stats.get("retry", 0)
    failed = stats.get("failed", 0)

    completion = (done / total * 100) if total > 0 else 0

    print("=" * 50)
    print("DMFW Details 采集进度")
    print("=" * 50)
    print(f"进度库: {args.state_db}")
    print(f"总任务数: {total:,}")
    print(f"  done:    {done:>10,}  ({done/total*100:.1f}%)" if total > 0 else f"  done:    {done:>10,}")
    print(f"  pending: {pending:>10,}")
    print(f"  claimed: {claimed:>10,}")
    print(f"  retry:   {retry:>10,}")
    print(f"  failed:  {failed:>10,}")
    print(f"完成率: {completion:.2f}%")

    last_updated = state.get_last_updated()
    if last_updated:
        print(f"最近更新: {last_updated}")

    # 估算剩余时间
    if done > 0 and pending > 0 and last_updated:
        try:
            last_dt = datetime.fromisoformat(last_updated)
            # 简单估算：假设 done 条用了 roughly last_updated - first_start 时间
            # 更简单的：最近一批 done 的速率
            remaining = pending + retry
            # 无法精确计算速率，给提示
            print(f"剩余待处理: {remaining:,}")
        except ValueError:
            pass

    # 总库信息
    try:
        master = MasterDB(args.master_db)
        master_count = master.count()
        print(f"总库记录数: {master_count:,}")
    except Exception as exc:
        print(f"总库: 无法连接 ({exc})")

    print("=" * 50)


if __name__ == "__main__":
    main()
