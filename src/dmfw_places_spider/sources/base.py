from __future__ import annotations

from abc import ABC, abstractmethod

from dmfw_places_spider.models.region import RegionNode


class AdministrativeSource(ABC):
    name: str

    @abstractmethod
    def fetch_regions(self) -> list[RegionNode]:
        raise NotImplementedError
