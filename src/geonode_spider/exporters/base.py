from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from geonode_spider.models.region import RegionNode


class BaseExporter(ABC):
    format_name: str

    @abstractmethod
    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        raise NotImplementedError
