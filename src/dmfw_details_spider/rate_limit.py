"""TokenBucket QPS 控制 + jitter + 指数退避。"""

from __future__ import annotations

import random
import time


class TokenBucket:
    """令牌桶 —— 精确 QPS 控制。"""

    def __init__(self, qps: float) -> None:
        if qps <= 0:
            qps = 0.1
        self.rate = qps
        self.interval = 1.0 / qps
        self._last_time = time.monotonic()
        self._tokens = 0.0

    def acquire(self) -> float:
        """获取一个令牌，返回实际等待的秒数。"""
        now = time.monotonic()
        elapsed = now - self._last_time
        self._last_time = now
        self._tokens += elapsed * self.rate
        if self._tokens > 1.0:
            self._tokens = 1.0

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        else:
            wait = (1.0 - self._tokens) / self.rate
            self._tokens = 0.0
            time.sleep(wait)
            return wait


def apply_jitter(base_interval: float, jitter_min: float, jitter_max: float) -> float:
    """在基础间隔上加随机 jitter。"""
    if jitter_max <= 0:
        return base_interval
    jitter_range = max(0.0, jitter_max - jitter_min)
    return base_interval + jitter_min + random.random() * jitter_range


def calculate_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    status_code: int | None = None,
) -> float:
    """计算退避延迟。

    - 429: 指数退避，至少 5s
    - 403: 指数退避，至少 30s
    - 5xx: 指数退避 (2^attempt + jitter)
    - timeout/connection: 线性退避 (base_delay * attempt)
    """
    if status_code == 429:
        delay = min(5.0 * (2 ** (attempt - 1)), max_delay)
    elif status_code == 403:
        delay = min(30.0 * (2 ** (attempt - 1)), max_delay)
    elif status_code and status_code >= 500:
        delay = min(base_delay * (2 ** attempt), max_delay)
    else:
        delay = min(base_delay * attempt, max_delay)

    # 加 jitter
    jitter = random.uniform(0, delay * 0.3)
    return delay + jitter


def should_retry(status_code: int | None, error: str | None) -> bool:
    """判断是否应该重试。"""
    if status_code == 429:
        return True
    if status_code == 403:
        return True  # 重试但会大幅退避
    if status_code and status_code >= 500:
        return True
    if error:
        if "超时" in error:
            return True
        if "连接错误" in error:
            return True
    return False
