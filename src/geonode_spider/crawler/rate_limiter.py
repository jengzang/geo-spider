from __future__ import annotations

import random
import time


class RateLimiter:
    def __init__(self, min_seconds: float, max_seconds: float, backoff_base_seconds: float) -> None:
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.backoff_base_seconds = backoff_base_seconds

    def wait(self, failure_count: int = 0) -> None:
        delay = random.uniform(self.min_seconds, self.max_seconds)
        if failure_count > 0:
            delay += self.backoff_base_seconds * failure_count
        if delay > 0:
            time.sleep(delay)
