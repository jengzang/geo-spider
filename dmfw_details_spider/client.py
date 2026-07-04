"""POST detailsPub 接口封装。"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


@dataclass(slots=True)
class FetchResult:
    id: str
    ok: bool
    status_code: int | None = None
    data: dict[str, Any] | None = None
    raw_text: str | None = None
    error: str | None = None
    elapsed_ms: float | None = None


class DetailsApiClient:
    """封装 detailsPub 接口请求。"""

    def __init__(
        self,
        base_url: str = "https://dmfw.mca.gov.cn",
        timeout: int = 10,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", random.choice(USER_AGENTS))

    def _rotate_ua(self) -> None:
        self.session.headers["User-Agent"] = random.choice(USER_AGENTS)

    def fetch_one(self, id_value: str) -> FetchResult:
        """请求单条地名详情。"""
        url = f"{self.base_url}/stname/detailsPub"
        self._rotate_ua()
        start = time.perf_counter()

        try:
            resp = self.session.post(
                url,
                data={"id": id_value},
                timeout=self.timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            raw_text = resp.text

            if not resp.ok:
                return FetchResult(
                    id=id_value,
                    ok=False,
                    status_code=resp.status_code,
                    raw_text=raw_text,
                    error=f"HTTP {resp.status_code}",
                    elapsed_ms=elapsed_ms,
                )

            try:
                data = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                return FetchResult(
                    id=id_value,
                    ok=False,
                    status_code=resp.status_code,
                    raw_text=raw_text,
                    error=f"JSON 解析失败: {exc}",
                    elapsed_ms=elapsed_ms,
                )

            return FetchResult(
                id=id_value,
                ok=True,
                status_code=resp.status_code,
                data=data,
                raw_text=raw_text,
                elapsed_ms=elapsed_ms,
            )

        except requests.Timeout:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return FetchResult(
                id=id_value,
                ok=False,
                error="请求超时",
                elapsed_ms=elapsed_ms,
            )
        except requests.ConnectionError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return FetchResult(
                id=id_value,
                ok=False,
                error=f"连接错误: {exc}",
                elapsed_ms=elapsed_ms,
            )
        except requests.RequestException as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return FetchResult(
                id=id_value,
                ok=False,
                error=f"请求异常: {exc}",
                elapsed_ms=elapsed_ms,
            )
