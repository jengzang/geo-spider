from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RequestProfile:
    timeout: int = 15
    retries: int = 3
    sleep_min_seconds: float = 0.5
    sleep_max_seconds: float = 1.5
    backoff_base_seconds: float = 1.0
    use_proxy: bool = False
