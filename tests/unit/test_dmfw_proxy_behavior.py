from __future__ import annotations

import requests

from geonode_spider.crawler.profile import RequestProfile
from geonode_spider.crawler.session import SpiderSession
from geonode_spider.services.dmfw import DmfwApiClient


def _build_session() -> SpiderSession:
    return SpiderSession(
        RequestProfile(
            timeout=1,
            retries=1,
            sleep_min_seconds=0,
            sleep_max_seconds=0,
            backoff_base_seconds=0,
            use_proxy=False,
        )
    )


def test_dmfw_api_client_bypasses_env_proxy_by_default() -> None:
    session = _build_session()

    DmfwApiClient("https://dmfw.mca.gov.cn", session=session)

    assert session.session.trust_env is False


def test_dmfw_api_client_can_keep_env_proxy_when_disabled() -> None:
    session = _build_session()
    session.session.trust_env = True

    DmfwApiClient("https://dmfw.mca.gov.cn", session=session, bypass_env_proxy=False)

    assert session.session.trust_env is True


def test_dmfw_api_client_preserves_injected_requests_session() -> None:
    injected = requests.Session()
    spider_session = SpiderSession(
        RequestProfile(
            timeout=1,
            retries=1,
            sleep_min_seconds=0,
            sleep_max_seconds=0,
            backoff_base_seconds=0,
            use_proxy=False,
        ),
        session=injected,
    )

    DmfwApiClient("https://dmfw.mca.gov.cn", session=spider_session)

    assert spider_session.session is injected
    assert injected.trust_env is False
