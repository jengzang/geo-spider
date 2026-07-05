from __future__ import annotations

import csv
from pathlib import Path

from dmfw_places_spider.exporters.base import BaseExporter, TabularRecord


class CsvExporter(BaseExporter):
    format_name = "csv"

    def export(self, records: list[TabularRecord], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        rows = [record.to_dict() for record in records]
        if not rows:
            destination.write_text("", encoding="utf-8")
            return destination
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return destination
