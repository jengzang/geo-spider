from __future__ import annotations

import random


DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0 Safari/537.36",
]


class DefaultUserAgentProvider:
    def __init__(self, user_agents: list[str] | None = None) -> None:
        self._user_agents = user_agents or DEFAULT_USER_AGENTS

    def get(self) -> str:
        return random.choice(self._user_agents)
