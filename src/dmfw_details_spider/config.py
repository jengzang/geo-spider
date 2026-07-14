"""配置 dataclass + 默认值 + CLI→Config 合并。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULTS = {
    "id_files": [],
    "id_file": "",
    "state_db": "data/processed/details_progress.sqlite",
    "master_db": "data/processed/dmfw_place_details_master.sqlite",
    "worker_output_dir": "data/interim/details_workers",
    "logs_dir": "logs/dmfw_details_spider",
    "workers": 1,
    "worker_id": "worker_001",
    "global_qps": 10.0,
    "per_worker_qps": 0.0,
    "request_interval": 0.0,
    "jitter_min": 0.002,
    "jitter_max": 0.01,
    "request_timeout": 10,
    "max_retries": 3,  # 保守默认，CLI 可覆盖
    "retry_base_delay": 1.0,
    "retry_max_delay": 60.0,
    "batch_size": 100,
    "claim_timeout_minutes": 30,
    "progress_flush_interval": 2000,
    "output_flush_interval": 100,
    "sync_ids_interval_seconds": 300,
    "merge_after_finish": False,
    "merge_interval": 0,
    "merge_batch_size": 5000,
    "delete_worker_db_after_merge": True,
    "dry_run": False,
    "sample_limit": 0,
    "base_url": "https://dmfw.mca.gov.cn",
    "log_level": "INFO",
    "output_db": "",
}


@dataclass(slots=True)
class Config:
    id_files: list[str] = field(default_factory=list)
    id_file: str = ""
    state_db: str = "data/processed/details_progress.sqlite"
    master_db: str = "data/processed/dmfw_place_details_master.sqlite"
    worker_output_dir: str = "data/interim/details_workers"
    logs_dir: str = "logs/dmfw_details_spider"
    workers: int = 1
    worker_id: str = "worker_001"
    global_qps: float = 10.0
    per_worker_qps: float = 0.0
    request_interval: float = 0.0
    jitter_min: float = 0.002
    jitter_max: float = 0.01
    request_timeout: int = 10
    max_retries: int = 10
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    batch_size: int = 100
    claim_timeout_minutes: int = 30
    progress_flush_interval: int = 2000
    output_flush_interval: int = 100
    sync_ids_interval_seconds: int = 300
    merge_after_finish: bool = False
    merge_interval: int = 0
    merge_batch_size: int = 5000
    delete_worker_db_after_merge: bool = True
    dry_run: bool = False
    sample_limit: int = 0
    base_url: str = "https://dmfw.mca.gov.cn"
    log_level: str = "INFO"
    output_db: str = ""


def load_config_file(path: str) -> dict:
    """从 YAML 或 JSON 文件加载配置，返回扁平 dict。

    YAML 需要 PyYAML 库；JSON 内置支持。
    """
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as f:
        if ext in (".yaml", ".yml"):
            try:
                import yaml as _yaml
            except ImportError:
                raise ImportError("读取 YAML 配置文件需要安装 PyYAML: pip install pyyaml")
            raw = _yaml.safe_load(f) or {}
        else:
            raw = json.load(f)

    # 支持嵌套结构（如 dmfw.workers → workers），也支持扁平 key
    result: dict = {}
    _flatten_keys(raw, "", result)
    return result


def _flatten_keys(data: dict, prefix: str, result: dict) -> None:
    for k, v in data.items():
        full_key = f"{prefix}{k}" if not prefix else k
        if isinstance(v, dict) and not any(
            full_key == f.name for f in dataclasses.fields(Config)  # type: ignore[attr-defined]
        ):
            _flatten_keys(v, f"{prefix}{k}.", result)
        else:
            result[full_key] = v


def build_config_from_args(args: object) -> Config:
    """从 argparse Namespace 构建 Config。

    优先级：显式 CLI 参数 > 配置文件 > Config 默认值。
    """
    config_fields = {f.name for f in dataclasses.fields(Config)}  # type: ignore[attr-defined]
    kwargs: dict = {}

    # 1) 配置文件覆盖 Config 默认值
    config_path = getattr(args, "config", None)
    if config_path:
        file_kwargs = load_config_file(config_path)
        for key, value in file_kwargs.items():
            if key in config_fields:
                kwargs[key] = value

    # 2) CLI 参数 —— 仅取用户显式传入的（不等于 argparse 默认值才算）或不在 DEFAULTS 里的
    for key, value in vars(args).items():
        if key == "config":
            continue
        if key not in config_fields:
            continue
        # 如果该 key 在 DEFAULTS 中且 value 等于默认值，说明用户没传，跳过
        if key in DEFAULTS and value == DEFAULTS[key]:
            continue
        # list 默认是空列表，用户没传时跳过
        if isinstance(value, list) and not value:
            continue
        kwargs[key] = value

    return Config(**kwargs)


import dataclasses
