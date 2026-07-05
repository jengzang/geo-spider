from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StaticProxyProvider:
    proxies: list[str] = field(default_factory=list)
    _index: int = 0

    def get_proxy(self) -> dict[str, str] | None:
        if not self.proxies:
            return None
        proxy = self.proxies[self._index % len(self.proxies)]
        self._index += 1
        return {"http": proxy, "https": proxy}

    def report_success(self, proxy: str | None) -> None:
        _ = proxy

    def report_failure(self, proxy: str | None) -> None:
        _ = proxy
