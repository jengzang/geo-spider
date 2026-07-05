from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values


DEFAULTS: dict[str, Any] = {
    "env": "development",
    "log_level": "INFO",
    "sqlite_path": "data/processed/dmfw_places_spider.db",
    "export_dir": "data/exports",
    "raw_dir": "data/raw",
    "interim_dir": "data/interim",
    "processed_dir": "data/processed",
    "request_timeout": 15,
    "request_retries": 3,
    "sleep_min_seconds": 0.5,
    "sleep_max_seconds": 1.5,
    "backoff_base_seconds": 1.0,
    "proxy_enabled": False,
    "proxy_pool": [],
    "geo_provider": "mock",
    "geo_api_key": "",
    "geo_endpoint": "",
    "dmfw_base_url": "https://dmfw.mca.gov.cn",
    "dmfw_bypass_env_proxy": True,
    "dmfw_page_size": 100,
    "dmfw_partition_threshold": 3000,
    "dmfw_search_type": "模糊",
}


@dataclass(slots=True)
class Settings:
    env: str = "development"
    log_level: str = "INFO"
    sqlite_path: Path = Path("data/processed/dmfw_places_spider.db")
    export_dir: Path = Path("data/exports")
    raw_dir: Path = Path("data/raw")
    interim_dir: Path = Path("data/interim")
    processed_dir: Path = Path("data/processed")
    request_timeout: int = 15
    request_retries: int = 3
    sleep_min_seconds: float = 0.5
    sleep_max_seconds: float = 1.5
    backoff_base_seconds: float = 1.0
    proxy_enabled: bool = False
    proxy_pool: list[str] | None = None
    geo_provider: str = "mock"
    geo_api_key: str = ""
    geo_endpoint: str = ""
    dmfw_base_url: str = "https://dmfw.mca.gov.cn"
    dmfw_bypass_env_proxy: bool = True
    dmfw_page_size: int = 100
    dmfw_partition_threshold: int = 3000
    dmfw_search_type: str = "模糊"

    def __post_init__(self) -> None:
        self.proxy_pool = list(self.proxy_pool or [])

    def to_display_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("sqlite_path", "export_dir", "raw_dir", "interim_dir", "processed_dir"):
            data[key] = str(data[key])
        return data


def load_settings(
    *,
    env_path: str | Path | None = None,
    yaml_path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> Settings:
    root = Path(project_root or Path.cwd()).resolve()
    env_file = Path(env_path) if env_path else root / ".env"
    yaml_file = Path(yaml_path) if yaml_path else root / "config" / "settings.yaml"

    merged = dict(DEFAULTS)
    merged.update(_load_yaml_values(yaml_file))
    merged.update(_load_env_values(env_file))
    merged.update(_load_os_env_values())

    return Settings(
        env=str(merged["env"]),
        log_level=str(merged["log_level"]).upper(),
        sqlite_path=_resolve_path(root, merged["sqlite_path"]),
        export_dir=_resolve_path(root, merged["export_dir"]),
        raw_dir=_resolve_path(root, merged["raw_dir"]),
        interim_dir=_resolve_path(root, merged["interim_dir"]),
        processed_dir=_resolve_path(root, merged["processed_dir"]),
        request_timeout=int(merged["request_timeout"]),
        request_retries=int(merged["request_retries"]),
        sleep_min_seconds=float(merged["sleep_min_seconds"]),
        sleep_max_seconds=float(merged["sleep_max_seconds"]),
        backoff_base_seconds=float(merged["backoff_base_seconds"]),
        proxy_enabled=_to_bool(merged["proxy_enabled"]),
        proxy_pool=_to_list(merged["proxy_pool"]),
        geo_provider=str(merged["geo_provider"]),
        geo_api_key=str(merged["geo_api_key"]),
        geo_endpoint=str(merged["geo_endpoint"]),
        dmfw_base_url=str(merged["dmfw_base_url"]),
        dmfw_bypass_env_proxy=_to_bool(merged["dmfw_bypass_env_proxy"]),
        dmfw_page_size=int(merged["dmfw_page_size"]),
        dmfw_partition_threshold=int(merged["dmfw_partition_threshold"]),
        dmfw_search_type=str(merged["dmfw_search_type"]),
    )


def _load_yaml_values(yaml_file: Path) -> dict[str, Any]:
    if not yaml_file.exists():
        return {}

    data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    return {
        "env": data.get("app", {}).get("env", DEFAULTS["env"]),
        "log_level": data.get("app", {}).get("log_level", DEFAULTS["log_level"]),
        "sqlite_path": data.get("paths", {}).get("sqlite_path", DEFAULTS["sqlite_path"]),
        "export_dir": data.get("paths", {}).get("export_dir", DEFAULTS["export_dir"]),
        "raw_dir": data.get("paths", {}).get("raw_dir", DEFAULTS["raw_dir"]),
        "interim_dir": data.get("paths", {}).get("interim_dir", DEFAULTS["interim_dir"]),
        "processed_dir": data.get("paths", {}).get("processed_dir", DEFAULTS["processed_dir"]),
        "request_timeout": data.get("crawler", {}).get("request_timeout", DEFAULTS["request_timeout"]),
        "request_retries": data.get("crawler", {}).get("request_retries", DEFAULTS["request_retries"]),
        "sleep_min_seconds": data.get("crawler", {}).get("sleep_min_seconds", DEFAULTS["sleep_min_seconds"]),
        "sleep_max_seconds": data.get("crawler", {}).get("sleep_max_seconds", DEFAULTS["sleep_max_seconds"]),
        "backoff_base_seconds": data.get("crawler", {}).get(
            "backoff_base_seconds",
            DEFAULTS["backoff_base_seconds"],
        ),
        "proxy_enabled": data.get("proxy", {}).get("enabled", DEFAULTS["proxy_enabled"]),
        "proxy_pool": data.get("proxy", {}).get("pool", DEFAULTS["proxy_pool"]),
        "geo_provider": data.get("geo", {}).get("provider", DEFAULTS["geo_provider"]),
        "geo_api_key": data.get("geo", {}).get("api_key", DEFAULTS["geo_api_key"]),
        "geo_endpoint": data.get("geo", {}).get("endpoint", DEFAULTS["geo_endpoint"]),
        "dmfw_base_url": data.get("dmfw", {}).get("base_url", DEFAULTS["dmfw_base_url"]),
        "dmfw_bypass_env_proxy": data.get("dmfw", {}).get(
            "bypass_env_proxy",
            DEFAULTS["dmfw_bypass_env_proxy"],
        ),
        "dmfw_page_size": data.get("dmfw", {}).get("page_size", DEFAULTS["dmfw_page_size"]),
        "dmfw_partition_threshold": data.get("dmfw", {}).get(
            "partition_threshold",
            DEFAULTS["dmfw_partition_threshold"],
        ),
        "dmfw_search_type": data.get("dmfw", {}).get("search_type", DEFAULTS["dmfw_search_type"]),
    }


def _load_env_values(env_file: Path) -> dict[str, Any]:
    if not env_file.exists():
        return {}
    env_values = dotenv_values(env_file)
    return _map_prefixed_env(env_values)


def _load_os_env_values() -> dict[str, Any]:
    prefixed = {
        key: value
        for key, value in os.environ.items()
        if key.startswith("GEONODE_")
    }
    return _map_prefixed_env(prefixed)


def _map_prefixed_env(values: dict[str, str | None]) -> dict[str, Any]:
    mapping: dict[str, tuple[str, Any]] = {
        "GEONODE_ENV": ("env", DEFAULTS["env"]),
        "GEONODE_LOG_LEVEL": ("log_level", DEFAULTS["log_level"]),
        "GEONODE_SQLITE_PATH": ("sqlite_path", DEFAULTS["sqlite_path"]),
        "GEONODE_EXPORT_DIR": ("export_dir", DEFAULTS["export_dir"]),
        "GEONODE_RAW_DIR": ("raw_dir", DEFAULTS["raw_dir"]),
        "GEONODE_INTERIM_DIR": ("interim_dir", DEFAULTS["interim_dir"]),
        "GEONODE_PROCESSED_DIR": ("processed_dir", DEFAULTS["processed_dir"]),
        "GEONODE_REQUEST_TIMEOUT": ("request_timeout", DEFAULTS["request_timeout"]),
        "GEONODE_REQUEST_RETRIES": ("request_retries", DEFAULTS["request_retries"]),
        "GEONODE_SLEEP_MIN_SECONDS": ("sleep_min_seconds", DEFAULTS["sleep_min_seconds"]),
        "GEONODE_SLEEP_MAX_SECONDS": ("sleep_max_seconds", DEFAULTS["sleep_max_seconds"]),
        "GEONODE_BACKOFF_BASE_SECONDS": ("backoff_base_seconds", DEFAULTS["backoff_base_seconds"]),
        "GEONODE_PROXY_ENABLED": ("proxy_enabled", DEFAULTS["proxy_enabled"]),
        "GEONODE_PROXY_POOL": ("proxy_pool", DEFAULTS["proxy_pool"]),
        "GEONODE_GEO_PROVIDER": ("geo_provider", DEFAULTS["geo_provider"]),
        "GEONODE_GEO_API_KEY": ("geo_api_key", DEFAULTS["geo_api_key"]),
        "GEONODE_GEO_ENDPOINT": ("geo_endpoint", DEFAULTS["geo_endpoint"]),
        "GEONODE_DMFW_BASE_URL": ("dmfw_base_url", DEFAULTS["dmfw_base_url"]),
        "GEONODE_DMFW_BYPASS_ENV_PROXY": (
            "dmfw_bypass_env_proxy",
            DEFAULTS["dmfw_bypass_env_proxy"],
        ),
        "GEONODE_DMFW_PAGE_SIZE": ("dmfw_page_size", DEFAULTS["dmfw_page_size"]),
        "GEONODE_DMFW_PARTITION_THRESHOLD": (
            "dmfw_partition_threshold",
            DEFAULTS["dmfw_partition_threshold"],
        ),
        "GEONODE_DMFW_SEARCH_TYPE": ("dmfw_search_type", DEFAULTS["dmfw_search_type"]),
    }
    parsed: dict[str, Any] = {}
    for env_key, (target_key, default) in mapping.items():
        value = values.get(env_key)
        if value in (None, "") and env_key != "GEONODE_PROXY_POOL":
            continue
        if env_key == "GEONODE_PROXY_POOL":
            if value is None:
                continue
            parsed[target_key] = _to_list(value or default)
            continue
        parsed[target_key] = value if value is not None else default
    return parsed


def _resolve_path(root: Path, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value).strip()]
