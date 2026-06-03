from __future__ import annotations

import requests

from geonode_spider.crawler.profile import RequestProfile
from geonode_spider.crawler.proxies import StaticProxyProvider
from geonode_spider.crawler.session import SpiderSession


class FakeRequestsSession:
    def __init__(self) -> None:
        self.proxies_seen: list[dict[str, str] | None] = []
        self.calls = 0

    def request(self, *, proxies=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        self.calls += 1
        self.proxies_seen.append(proxies)
        if self.calls == 1:
            raise requests.RequestException("temporary failure")
        return FakeResponse()


class FakeResponse:
    def raise_for_status(self) -> None:
        return None


def test_spider_session_retries_with_next_proxy() -> None:
    profile = RequestProfile(
        timeout=5,
        retries=2,
        sleep_min_seconds=0.0,
        sleep_max_seconds=0.0,
        backoff_base_seconds=0.0,
        use_proxy=True,
    )
    provider = StaticProxyProvider(
        proxies=[
            "http://proxy-a.example:8080",
            "http://proxy-b.example:8080",
        ]
    )
    fake_session = FakeRequestsSession()
    spider = SpiderSession(profile, proxy_provider=provider, session=fake_session)

    spider.get("https://example.com/data")

    assert fake_session.proxies_seen == [
        {"http": "http://proxy-a.example:8080", "https": "http://proxy-a.example:8080"},
        {"http": "http://proxy-b.example:8080", "https": "http://proxy-b.example:8080"},
    ]
