from __future__ import annotations

from typing import Any

import requests

from geonode_spider.crawler.profile import RequestProfile
from geonode_spider.crawler.proxies import StaticProxyProvider
from geonode_spider.crawler.rate_limiter import RateLimiter
from geonode_spider.crawler.user_agents import DefaultUserAgentProvider


class SpiderSession:
    def __init__(
        self,
        profile: RequestProfile,
        *,
        user_agent_provider: DefaultUserAgentProvider | None = None,
        proxy_provider: StaticProxyProvider | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.profile = profile
        self.user_agent_provider = user_agent_provider or DefaultUserAgentProvider()
        self.proxy_provider = proxy_provider or StaticProxyProvider()
        self.session = session or requests.Session()
        self.rate_limiter = RateLimiter(
            min_seconds=profile.sleep_min_seconds,
            max_seconds=profile.sleep_max_seconds,
            backoff_base_seconds=profile.backoff_base_seconds,
        )

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        failures = 0
        last_error: Exception | None = None

        for _ in range(self.profile.retries):
            self.rate_limiter.wait(failures)
            headers = dict(kwargs.pop("headers", {}))
            headers.setdefault("User-Agent", self.user_agent_provider.get())
            proxies = kwargs.pop("proxies", None)
            if proxies is None and self.profile.use_proxy:
                proxies = self.proxy_provider.get_proxy()

            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    timeout=self.profile.timeout,
                    headers=headers,
                    proxies=proxies,
                    **kwargs,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                failures += 1
                last_error = exc

        if last_error is None:
            raise RuntimeError("request failed without an exception")
        raise last_error

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)
