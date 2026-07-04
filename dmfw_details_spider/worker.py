"""单 worker 主循环。"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone

from dmfw_details_spider.cli import add_common_args, add_id_file_args, add_worker_args, add_run_args
from dmfw_details_spider.config import DEFAULTS, Config, build_config_from_args
from dmfw_details_spider.client import DetailsApiClient, FetchResult
from dmfw_details_spider.id_pool import iter_ids_from_file, count_lines_in_file
from dmfw_details_spider.output_db import OutputDB
from dmfw_details_spider.rate_limit import TokenBucket, apply_jitter, calculate_backoff, should_retry
from dmfw_details_spider.state_db import StateDB

logger = logging.getLogger(__name__)

_shutdown_requested = False
_flush_on_exit: object = None  # 退出时调用的 flush 函数，由 run_worker 设置


def _handle_signal(signum: int, frame: object) -> None:
    global _shutdown_requested, _flush_on_exit
    if not _shutdown_requested:
        logger.info("收到退出信号，等待当前批次完成...")
        _shutdown_requested = True
        if callable(_flush_on_exit):
            _flush_on_exit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_record(result: FetchResult, attempt: int, worker_id: str) -> dict:
    """从 FetchResult 提取入库记录。"""
    data = result.data or {}
    gdm = data.get("gdm") or {}

    record = {
        "id": result.id,
        "place_code": data.get("place_code"),
        "standard_name": data.get("standard_name"),
        "old_name": data.get("old_name"),
        "place_type": data.get("place_type"),
        "place_type_code": data.get("place_type_code"),
        "province_name": data.get("province_name"),
        "city_name": data.get("city_name"),
        "area_name": data.get("area_name"),
        "province": data.get("province"),
        "city": data.get("city"),
        "area": data.get("area"),
        "roman_alphabet_spelling": data.get("roman_alphabet_spelling"),
        "ethnic_minorities_writing": data.get("ethnic_minorities_writing"),
        "place_origin": data.get("place_origin"),
        "place_meaning": data.get("place_meaning"),
        "place_history": data.get("place_history"),
        "government_history": data.get("government_history"),
        "geometry_type": gdm.get("type") if isinstance(gdm, dict) else None,
        "coordinates_json": (
            _safe_json_dumps(gdm.get("coordinates")) if isinstance(gdm, dict) else None
        ),
        "gdm_json": _safe_json_dumps(gdm) if gdm else None,
        "raw_json": result.raw_text or "",
        "response_status_code": result.status_code,
        "fetched_at": _now_iso(),
        "worker_id": worker_id,
        "attempt": attempt,
        "error": result.error if not result.ok else None,
    }
    return record


def _safe_json_dumps(obj: object) -> str | None:
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj) if obj is not None else None


def run_worker(config: Config) -> int:
    """单 worker 主逻辑。返回处理的 done 数量。"""
    global _shutdown_requested

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    state_db = StateDB(config.state_db)
    state_db.initialize()

    output_db = OutputDB(config.output_db)
    if not config.output_db:
        logger.error("worker 需要 --output-db 参数")
        return 0
    output_db.initialize()

    client = DetailsApiClient(base_url=config.base_url, timeout=config.request_timeout)

    # QPS 控制：per_worker_qps 优先，其次 global_qps/workers
    if config.request_interval > 0:
        interval = config.request_interval
    elif config.per_worker_qps > 0:
        interval = 1.0 / config.per_worker_qps
    else:
        interval = 1.0 / max(0.1, config.global_qps / max(1, config.workers))
    per_qps = 1.0 / interval if interval > 0 else 0
    bucket = TokenBucket(per_qps)

    # 读取 worker 专属 ID 文件
    id_file = getattr(config, "id_file", "")
    if not id_file or not os.path.isfile(id_file):
        logger.warning(f"worker {config.worker_id}: 无 ID 文件，退出")
        return 0

    try:
        total_ids = count_lines_in_file(id_file)
    except Exception:
        total_ids = 0
    logger.info(
        f"worker {config.worker_id} 启动: {total_ids:,} IDs, per_qps={per_qps:.2f}, "
        f"timeout={config.request_timeout}s, max_retries={config.max_retries}"
    )

    if config.dry_run:
        logger.info("*** DRY RUN 模式 —— 不发送实际 HTTP 请求 ***")

    success = 0
    failed = 0
    total_retries = 0
    processed = 0
    start_time = time.monotonic()

    # 本地累积的进度更新，批量写 state_db 减少锁竞争
    done_ids: list[str] = []
    retry_updates: list[tuple[str, str, str]] = []
    failed_updates: list[tuple[str, str, str]] = []

    # 成功记录缓冲，每 100 条批量写一次自己的输出库
    BULK_FLUSH = 100
    ok_buffer: list[dict] = []

    last_flush = time.monotonic()

    def _flush_output_db() -> None:
        """批量写成功记录到自己的输出库。"""
        nonlocal ok_buffer
        if ok_buffer:
            output_db.bulk_upsert(ok_buffer)
            ok_buffer.clear()

    def _flush_progress() -> None:
        """批量提交本地的进度更新到 state_db。"""
        nonlocal done_ids, retry_updates, failed_updates, last_flush
        if done_ids:
            state_db.bulk_mark_done(done_ids)
            done_ids.clear()
        if retry_updates:
            state_db.bulk_mark_status(retry_updates)
            retry_updates.clear()
        if failed_updates:
            state_db.bulk_mark_status(failed_updates)
            failed_updates.clear()
        last_flush = time.monotonic()

    # 退出时确保 flush
    def _shutdown_flush() -> None:
        _flush_output_db()
        if done_ids or retry_updates or failed_updates:
            logger.info(
                f"退出前同步进度: done={len(done_ids)} "
                f"retry={len(retry_updates)} failed={len(failed_updates)}"
            )
            _flush_progress()

    global _flush_on_exit
    _flush_on_exit = _shutdown_flush

    for id_val in iter_ids_from_file(id_file):
        if _shutdown_requested:
            break
        if config.sample_limit > 0 and processed >= config.sample_limit:
            logger.info(f"达到 sample_limit={config.sample_limit}，停止")
            break
        processed += 1

        # 请求 + 重试
        result = None
        for attempt in range(1, config.max_retries + 1):
            if _shutdown_requested:
                break

            if not config.dry_run:
                # QPS 控制：TokenBucket + 微量 jitter
                if attempt == 1:
                    wait = bucket.acquire()
                    jitter = random.uniform(config.jitter_min, config.jitter_max)
                    if jitter > 0:
                        time.sleep(jitter)

                result = client.fetch_one(id_val)
            else:
                result = FetchResult(
                    id=id_val, ok=True, status_code=200,
                    data={"id": id_val, "standard_name": f"dry_run_{id_val}"},
                    raw_text='{"id": "' + id_val + '"}', elapsed_ms=0,
                )

            if result.ok:
                break

            total_retries += 1
            if attempt < config.max_retries and should_retry(result.status_code, result.error):
                backoff = calculate_backoff(
                    attempt,
                    base_delay=config.retry_base_delay,
                    max_delay=config.retry_max_delay,
                    status_code=result.status_code,
                )
                # 500 时输出响应体前 200 字符帮助排查
                body_preview = ""
                if result.status_code and result.status_code >= 500 and result.raw_text:
                    body_preview = result.raw_text[:200].replace("\n", " ")
                logger.warning(
                    f"  [{id_val}] 第{attempt}次失败: {result.error} "
                    f"status={result.status_code}, 退避 {backoff:.1f}s"
                    f"{' body=' + body_preview if body_preview else ''}"
                )
                if result.status_code == 403:
                    logger.error(
                        f"  [{id_val}] 403 Forbidden —— 显著降速 30s，"
                        "避免反复冲击"
                    )
                time.sleep(backoff)

        if result is None:
            result = FetchResult(id=id_val, ok=False, error="worker 退出中断")

        # 仅成功才写入输出库，失败的等重试
        if result.ok:
            record = _extract_record(result, attempt, config.worker_id)
            if not config.dry_run:
                ok_buffer.append(record)
                done_ids.append(id_val)
            success += 1
        elif attempt < config.max_retries:
            if not config.dry_run:
                retry_updates.append((id_val, "retry", result.error or "未知错误"))
            failed += 1
        else:
            if not config.dry_run:
                failed_updates.append((id_val, "failed", result.error or "超过最大重试次数"))
            failed += 1

        # 每 BULK_FLUSH 条批量写一次自己的输出库
        if len(ok_buffer) >= BULK_FLUSH:
            _flush_output_db()

        # 进度日志
        if processed % 100 == 0:
            elapsed = time.monotonic() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            logger.info(
                f"进度: success={success} failed={failed} "
                f"率={rate:.1f}/s 本地缓冲done={len(done_ids)}"
            )

        # 达到阈值才提交进度
        if not config.dry_run:
            total_buffered = len(done_ids) + len(retry_updates) + len(failed_updates)
            if total_buffered >= config.progress_flush_interval:
                logger.info(f"flush 进度到 state_db: done={len(done_ids)} retry={len(retry_updates)} failed={len(failed_updates)}")
                _flush_progress()

    # 正常退出前 flush 剩余进度
    _shutdown_flush()

    elapsed = time.monotonic() - start_time
    rate = processed / elapsed if elapsed > 0 else 0
    logger.info(
        f"[WORKER_SUMMARY] worker_id={config.worker_id} "
        f"processed={processed} success={success} failed={failed} "
        f"retries={total_retries} elapsed={elapsed:.0f}s rate={rate:.1f}/s"
    )
    _flush_on_exit = None
    return success


def main() -> None:
    parser = argparse.ArgumentParser(description="DMFW 单 worker 采集")
    add_common_args(parser)
    add_id_file_args(parser)
    add_worker_args(parser)
    add_run_args(parser)
    parser.add_argument("--worker-id", default=DEFAULTS["worker_id"])
    parser.add_argument("--output-db", default="", help="worker 临时输出库路径")
    parser.add_argument(
        "--per-worker-qps",
        type=float,
        default=DEFAULTS["per_worker_qps"],
        help="每 worker QPS (0=由 global_qps/workers 计算)",
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config = build_config_from_args(args)
    if config.per_worker_qps <= 0 and config.request_interval <= 0:
        config.per_worker_qps = config.global_qps / max(1, config.workers)
    if args.output_db:
        config.output_db = args.output_db

    if not config.output_db:
        logger.error("需要 --output-db 参数")
        raise SystemExit(1)

    code = run_worker(config)
    raise SystemExit(0 if code >= 0 else 1)


if __name__ == "__main__":
    main()
