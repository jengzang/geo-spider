"""QPS 阶梯探测命令。"""

from __future__ import annotations

import argparse
import logging
import random
import statistics
import time

from dmfw_details_spider.cli import add_common_args
from dmfw_details_spider.config import DEFAULTS
from dmfw_details_spider.id_pool import iter_ids_from_file
from dmfw_details_spider.client import DetailsApiClient, FetchResult

logger = logging.getLogger(__name__)


def _run_level(
    client: DetailsApiClient,
    ids: list[str],
    qps: float,
    duration: float,
) -> dict:
    """以指定 QPS 请求样本，返回统计。"""
    interval = 1.0 / qps if qps > 0 else 1.0
    start_time = time.monotonic()
    end_time = start_time + duration

    latencies: list[float] = []
    ok_count = 0
    fail_count = 0
    status_counts: dict[int, int] = {}
    error_types: dict[str, int] = {}
    json_failures = 0

    idx = 0
    while time.monotonic() < end_time and idx < len(ids):
        loop_start = time.monotonic()

        id_val = ids[idx % len(ids)]
        idx += 1
        result = client.fetch_one(id_val)

        if result.elapsed_ms is not None:
            latencies.append(result.elapsed_ms)

        if result.ok:
            ok_count += 1
        else:
            fail_count += 1
            if result.status_code:
                status_counts[result.status_code] = status_counts.get(result.status_code, 0) + 1
            if result.error:
                err_key = result.error.split(":")[0].strip()
                error_types[err_key] = error_types.get(err_key, 0) + 1
                if "JSON" in (result.error or ""):
                    json_failures += 1

        # QPS 控制
        elapsed = time.monotonic() - loop_start
        sleep_time = max(0, interval - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    total = ok_count + fail_count
    success_rate = ok_count / total * 100 if total > 0 else 0

    p50 = statistics.median(latencies) if latencies else 0
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else (max(latencies) if latencies else 0)
    p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else (max(latencies) if latencies else 0)
    avg = statistics.mean(latencies) if latencies else 0

    return {
        "qps": qps,
        "total": total,
        "ok": ok_count,
        "fail": fail_count,
        "success_rate": success_rate,
        "avg_latency_ms": avg,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "status_429": status_counts.get(429, 0),
        "status_403": status_counts.get(403, 0),
        "status_5xx": sum(v for k, v in status_counts.items() if k >= 500),
        "timeouts": error_types.get("请求超时", 0),
        "json_failures": json_failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="QPS 阶梯探测")
    add_common_args(parser)
    parser.add_argument(
        "--id-file",
        required=True,
        help="采样 ID 文件",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="采样数量 (默认: 100)",
    )
    parser.add_argument(
        "--qps-levels",
        default="1,2,5,10,20,30,50",
        help="QPS 阶梯 (默认: 1,2,5,10,20,30,50)",
    )
    parser.add_argument(
        "--duration-per-level",
        type=int,
        default=30,
        help="每档持续时间秒 (默认: 30)",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=DEFAULTS["request_timeout"],
        help=f"请求超时秒数 (默认: {DEFAULTS['request_timeout']})",
    )

    args = parser.parse_args()
    import logging as _logging
    _logging.basicConfig(
        level=getattr(_logging, args.log_level.upper(), _logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 采样 ID
    all_ids = list(iter_ids_from_file(args.id_file))
    if len(all_ids) > args.sample_size:
        sample_ids = random.sample(all_ids, args.sample_size)
    else:
        sample_ids = all_ids
    logger.info(f"采样 {len(sample_ids)} 个 ID (总 ID 数: {len(all_ids):,})")

    levels = [float(x.strip()) for x in args.qps_levels.split(",")]

    client = DetailsApiClient(timeout=args.request_timeout)

    print()
    print("=" * 80)
    print(f"{'QPS':>6}  {'总数':>6}  {'成功':>6}  {'成功率':>8}  "
          f"{'Avg':>8}  {'P50':>8}  {'P95':>8}  {'P99':>8}  "
          f"{'429':>5}  {'403':>5}  {'5xx':>5}  {'超时':>5}  {'JSON失败':>8}")
    print("-" * 80)

    results = []
    stop_next = False
    for qps in levels:
        if stop_next:
            logger.info(f"跳过 {qps} qps (前挡异常)")
            break

        logger.info(f"测试 QPS={qps}...")
        result = _run_level(client, sample_ids, qps, args.duration_per_level)
        results.append(result)

        print(
            f"{result['qps']:>6.0f}  {result['total']:>6}  {result['ok']:>6}  "
            f"{result['success_rate']:>7.1f}%  "
            f"{result['avg_latency_ms']:>7.0f}ms {result['p50_ms']:>7.0f}ms "
            f"{result['p95_ms']:>7.0f}ms {result['p99_ms']:>7.0f}ms  "
            f"{result['status_429']:>5}  {result['status_403']:>5}  "
            f"{result['status_5xx']:>5}  {result['timeouts']:>5}  "
            f"{result['json_failures']:>8}"
        )

        # 判断是否应该停止
        if result["status_429"] > 0 or result["status_403"] > 0:
            logger.warning(f"QPS={qps}: 出现 429/403，停止继续提高")
            stop_next = True
        elif result["success_rate"] < 90:
            logger.warning(f"QPS={qps}: 成功率低于 90%，停止继续提高")
            stop_next = True

    # 安全建议
    print()
    print("=" * 50)
    good_results = [r for r in results if r["success_rate"] >= 95 and r["status_429"] == 0 and r["status_403"] == 0]
    if good_results:
        safe_r = good_results[-1]
        safe_qps = safe_r["qps"] * 0.7
        print(f"建议安全 QPS: {safe_qps:.1f} (最高稳定 QPS {safe_r['qps']:.0f} 的 70%)")
        print(f"参考: 稳定档 QPS={safe_r['qps']:.0f}, 成功率={safe_r['success_rate']:.1f}%, "
              f"P95={safe_r['p95_ms']:.0f}ms")
    else:
        print("未找到稳定 QPS 档位，建议从 QPS=1 开始")
    print("=" * 50)


if __name__ == "__main__":
    main()
