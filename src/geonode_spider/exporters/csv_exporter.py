from __future__ import annotations

import csv
from pathlib import Path

from geonode_spider.exporters.base import BaseExporter
from geonode_spider.models.region import RegionNode


class CsvExporter(BaseExporter):
    format_name = "csv"

    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        rows = [region.to_dict() for region in regions]
        if not rows:
            destination.write_text("", encoding="utf-8")
            return destination
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return destination
