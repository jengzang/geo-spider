"""多 worker 启动器 —— ProcessPoolExecutor。"""

from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import os
import shutil
import signal
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone

from dmfw_details_spider.cli import (
    add_common_args,
    add_id_file_args,
    add_merge_args,
    add_run_args,
    add_worker_args,
)
from dmfw_details_spider.config import DEFAULTS, Config, build_config_from_args
from dmfw_details_spider.output_db import MasterDB, merge_run_directory
from dmfw_details_spider.state_db import StateDB

logger = logging.getLogger(__name__)

WORKER_MODULE = "dmfw_details_spider.worker"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_run_id() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M%S")


def _init_worker() -> None:
    """Worker 进程忽略 SIGINT，由父进程协调退出。"""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def _worker_entry(
    worker_id: str,
    config_dict: dict,
) -> int:
    """Worker 进程入口。接收 dict 配置（跨进程序列化）。"""
    import logging

    # 为子进程重新设置日志（包含 pid）
    logging.basicConfig(
        level=getattr(logging, config_dict.get("log_level", "INFO"), logging.INFO),
        format=f"%(asctime)s [%(levelname)s] {worker_id}: %(message)s",
    )

    # 重建 Config
    cfg = Config(**{k: v for k, v in config_dict.items() if k in Config.__slots__})  # type: ignore[call-arg]

    # worker 输出库路径
    run_dir = cfg.worker_output_dir
    worker_db = os.path.join(run_dir, f"{worker_id}.sqlite")
    cfg.output_db = worker_db
    cfg.worker_id = worker_id

    # 计算 per_worker_qps
    if cfg.request_interval <= 0 and cfg.per_worker_qps <= 0:
        cfg.per_worker_qps = cfg.global_qps / max(1, cfg.workers)

    from dmfw_details_spider.worker import run_worker
    return run_worker(cfg)


def launch(config: Config) -> int:
    """启动多 worker，返回各 worker 处理的 done 数之和。"""
    state_db = StateDB(config.state_db)
    state_db.initialize()

    # 自动同步 ID 池（增量，已存在的不影响）
    if config.id_files:
        from dmfw_details_spider.id_pool import iter_ids_from_files
        logger.info(f"自动同步 ID 池: {len(config.id_files)} 个文件...")
        result = state_db.sync_ids(iter_ids_from_files(config.id_files))
        logger.info(
            f"ID 池同步完成: 新增 {result['added']:,}, "
            f"已存在 {result['existed']:,}"
        )

    run_id = _generate_run_id()
    run_dir = os.path.join(config.worker_output_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)

    n_workers = max(1, config.workers)
    logger.info(
        f"启动 {n_workers} 个 worker, run_id={run_id}, "
        f"global_qps={config.global_qps}, per_worker_qps={config.global_qps / n_workers:.2f}, "
        f"batch_size={config.batch_size}"
    )

    # 准备传给 worker 的配置 dict
    config_dict = {
        k: getattr(config, k)
        for k in Config.__slots__  # type: ignore[attr-defined]
        if hasattr(config, k)
    }
    config_dict["worker_output_dir"] = run_dir

    mp_context = mp.get_context("spawn")
    total_done = 0
    interrupted = False

    try:
        with ProcessPoolExecutor(
            max_workers=n_workers,
            mp_context=mp_context,
            initializer=_init_worker,
        ) as executor:
            futures = {}
            for i in range(n_workers):
                worker_id = f"worker_{i + 1:03d}"
                worker_config = dict(config_dict)
                worker_config["worker_id"] = worker_id
                fut = executor.submit(_worker_entry, worker_id, worker_config)
                futures[fut] = worker_id

            for fut in as_completed(futures):
                worker_id = futures[fut]
                try:
                    done = fut.result()
                    total_done += done
                    logger.info(f"[{worker_id}] 完成，处理 {done} 条")
                except Exception as exc:
                    logger.error(f"[{worker_id}] 异常退出: {exc}")

    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，等待 worker flush 进度...")
        interrupted = True
        time.sleep(3)  # 给 worker 的 SIGINT 处理器时间 flush
        # 不 raise，继续执行 merge

    logger.info(f"所有 worker 结束，总计 done={total_done}")

    # 合并（正常结束或 Ctrl+C 都会执行）
    if config.merge_after_finish or interrupted:
        logger.info("开始汇总到总库...")
        master = MasterDB(config.master_db)
        master.initialize()
        result = merge_run_directory(
            run_dir, master, run_id,
            delete_after=config.delete_worker_db_after_merge,
        )
        logger.info(
            f"汇总完成: 扫描 {result['scanned']} 个库, "
            f"读取 {result['total_read']:,}, "
            f"新增 ~{result['total_inserted']:,}, "
            f"更新 ~{result['total_updated']:,}, "
            f"异常 {result['total_errors']}"
        )
        total_in_master = master.count()
        logger.info(f"总库当前记录数: {total_in_master:,}")

    # Ctrl+C 后清理 run 目录
    if interrupted:
        try:
            if os.path.isdir(run_dir):
                shutil.rmtree(run_dir, ignore_errors=True)
                logger.info(f"已清理 run 目录: {run_dir}")
        except Exception:
            pass

    return total_done


def main() -> None:
    parser = argparse.ArgumentParser(description="DMFW 多 worker 启动器")
    add_common_args(parser)
    add_id_file_args(parser)
    add_worker_args(parser)
    add_merge_args(parser)
    add_run_args(parser)

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = build_config_from_args(args)
    try:
        done = launch(config)
        logger.info(f"launch 完成: total_done={done}")
    except KeyboardInterrupt:
        logger.info("启动器收到中断信号，已退出")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
