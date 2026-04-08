from __future__ import annotations

from abc import ABC, abstractmethod

from geonode_spider.models.region import RegionNode


class GeoCoder(ABC):
    @abstractmethod
    def enrich(self, regions: list[RegionNode]) -> list[RegionNode]:
        raise NotImplementedError
