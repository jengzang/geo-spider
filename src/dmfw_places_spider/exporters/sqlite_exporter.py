from __future__ import annotations

from pathlib import Path

from dmfw_places_spider.exporters.base import BaseExporter
from dmfw_places_spider.models.region import RegionNode
from dmfw_places_spider.storage.sqlite import SQLiteRegionRepository


class SqliteExporter(BaseExporter):
    format_name = "db"

    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        if destination.exists():
            destination.unlink()
        repository = SQLiteRegionRepository(destination)
        repository.initialize()
        repository.upsert_regions(regions)
        return destination
