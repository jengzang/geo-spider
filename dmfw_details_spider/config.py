"""配置 dataclass + 默认值 + CLI→Config 合并。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULTS = {
    "id_files": [],
    "state_db": "crawler_state/details_progress.sqlite",
    "master_db": "crawler_output/dmfw_place_details_master.sqlite",
    "worker_output_dir": "crawler_output/workers",
    "logs_dir": "logs/dmfw_details_spider",
    "workers": 1,
    "worker_id": "worker_001",
    "global_qps": 10.0,
    "per_worker_qps": 0.0,
    "request_interval": 0.0,
    "jitter_min": 0.05,
    "jitter_max": 0.3,
    "request_timeout": 10,
    "max_retries": 3,
    "retry_base_delay": 1.0,
    "retry_max_delay": 60.0,
    "batch_size": 100,
    "claim_timeout_minutes": 30,
    "sync_ids_interval_seconds": 300,
    "merge_after_finish": False,
    "delete_worker_db_after_merge": False,
    "dry_run": False,
    "sample_limit": 0,
    "base_url": "https://dmfw.mca.gov.cn",
    "log_level": "INFO",
    "output_db": "",
}


@dataclass(slots=True)
class Config:
    id_files: list[str] = field(default_factory=list)
    state_db: str = "crawler_state/details_progress.sqlite"
    master_db: str = "crawler_output/dmfw_place_details_master.sqlite"
    worker_output_dir: str = "crawler_output/workers"
    logs_dir: str = "logs/dmfw_details_spider"
    workers: int = 1
    worker_id: str = "worker_001"
    global_qps: float = 10.0
    per_worker_qps: float = 0.0
    request_interval: float = 0.0
    jitter_min: float = 0.05
    jitter_max: float = 0.3
    request_timeout: int = 10
    max_retries: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    batch_size: int = 100
    claim_timeout_minutes: int = 30
    sync_ids_interval_seconds: int = 300
    merge_after_finish: bool = False
    delete_worker_db_after_merge: bool = False
    dry_run: bool = False
    sample_limit: int = 0
    base_url: str = "https://dmfw.mca.gov.cn"
    log_level: str = "INFO"
    output_db: str = ""


def build_config_from_args(args: object) -> Config:
    """从 argparse Namespace 构建 Config，只取 Config 中存在的字段。"""
    config_fields = {f.name for f in dataclasses.fields(Config)}  # type: ignore[attr-defined]
    kwargs = {}
    for key, value in vars(args).items():
        if key in config_fields and value is not None:
            kwargs[key] = value
    return Config(**kwargs)


import dataclasses
