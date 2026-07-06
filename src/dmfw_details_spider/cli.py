"""公共 CLI 参数 —— 被各模块复用。"""

from __future__ import annotations

import argparse

from dmfw_details_spider.config import DEFAULTS


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """所有子命令共享的通用参数。"""
    parser.add_argument(
        "--config",
        help="YAML/JSON 配置文件路径",
    )
    parser.add_argument(
        "--state-db",
        default=DEFAULTS["state_db"],
        help=f"共享进度库路径 (默认: {DEFAULTS['state_db']})",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULTS["log_level"],
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help=f"日志级别 (默认: {DEFAULTS['log_level']})",
    )


def add_id_file_args(parser: argparse.ArgumentParser) -> None:
    """ID 文件相关参数。"""
    parser.add_argument(
        "--id-file",
        dest="id_files",
        action="append",
        default=[],
        help="ID 文件路径 (可重复指定多个)",
    )


def add_worker_args(parser: argparse.ArgumentParser) -> None:
    """worker/launch 专用参数。"""
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULTS["workers"],
        help=f"worker 数量 (默认: {DEFAULTS['workers']})",
    )
    parser.add_argument(
        "--global-qps",
        type=float,
        default=DEFAULTS["global_qps"],
        help=f"全局 QPS 上限 (默认: {DEFAULTS['global_qps']})",
    )
    parser.add_argument(
        "--request-interval",
        type=float,
        default=DEFAULTS["request_interval"],
        help="每请求间隔秒数 (优先级高于 global-qps 自动计算)",
    )
    parser.add_argument(
        "--jitter-min",
        type=float,
        default=DEFAULTS["jitter_min"],
        help=f"jitter 最小值 (默认: {DEFAULTS['jitter_min']})",
    )
    parser.add_argument(
        "--jitter-max",
        type=float,
        default=DEFAULTS["jitter_max"],
        help=f"jitter 最大值 (默认: {DEFAULTS['jitter_max']})",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=DEFAULTS["request_timeout"],
        help=f"请求超时秒数 (默认: {DEFAULTS['request_timeout']})",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULTS["max_retries"],
        help=f"最大重试次数 (默认: {DEFAULTS['max_retries']})",
    )
    parser.add_argument(
        "--retry-base-delay",
        type=float,
        default=DEFAULTS["retry_base_delay"],
        help=f"重试基础延迟秒数 (默认: {DEFAULTS['retry_base_delay']})",
    )
    parser.add_argument(
        "--retry-max-delay",
        type=float,
        default=DEFAULTS["retry_max_delay"],
        help=f"重试最大延迟秒数 (默认: {DEFAULTS['retry_max_delay']})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULTS["batch_size"],
        help=f"每批领取 ID 数 (默认: {DEFAULTS['batch_size']})",
    )
    parser.add_argument(
        "--claim-timeout-minutes",
        type=int,
        default=DEFAULTS["claim_timeout_minutes"],
        help=f"claimed 超时分钟数 (默认: {DEFAULTS['claim_timeout_minutes']})",
    )


def add_run_args(parser: argparse.ArgumentParser) -> None:
    """运行控制参数。"""
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=DEFAULTS["dry_run"],
        help="干跑模式，不发实际 HTTP 请求",
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=DEFAULTS["sample_limit"],
        help="限制处理条数 (0=不限制)",
    )


def add_merge_args(parser: argparse.ArgumentParser) -> None:
    """merge 相关参数。"""
    parser.add_argument(
        "--master-db",
        default=DEFAULTS["master_db"],
        help=f"总库路径 (默认: {DEFAULTS['master_db']})",
    )
    parser.add_argument(
        "--worker-output-dir",
        default=DEFAULTS["worker_output_dir"],
        help=f"worker 输出目录 (默认: {DEFAULTS['worker_output_dir']})",
    )
    parser.add_argument(
        "--merge-after-finish",
        action="store_true",
        default=DEFAULTS["merge_after_finish"],
        help="所有 worker 结束后自动汇总到总库",
    )
    parser.add_argument(
        "--merge-batch-size",
        type=int,
        default=DEFAULTS["merge_batch_size"],
        help=f"合并总库时每批写入条数 (默认: {DEFAULTS['merge_batch_size']})",
    )
    parser.add_argument(
        "--delete-worker-db-after-merge",
        action="store_true",
        default=DEFAULTS["delete_worker_db_after_merge"],
        help="汇总成功后删除 worker 临时库",
    )
