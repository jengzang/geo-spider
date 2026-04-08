from __future__ import annotations

from pathlib import Path

from geonode_spider.exporters.base import BaseExporter
from geonode_spider.models.region import RegionNode
from geonode_spider.storage.sqlite import SQLiteRegionRepository


class SqliteExporter(BaseExporter):
    format_name = "db"

    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        if destination.exists():
            destination.unlink()
        repository = SQLiteRegionRepository(destination)
        repository.initialize()
        repository.upsert_regions(regions)
        return destination
