from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from geonode_spider.exporters.base import BaseExporter
from geonode_spider.models.region import RegionNode


class ExcelExporter(BaseExporter):
    format_name = "xlsx"

    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "regions"
        rows = [region.to_dict() for region in regions]
        if rows:
            headers = list(rows[0].keys())
            sheet.append(headers)
            for row in rows:
                sheet.append([row[header] for header in headers])
        workbook.save(destination)
        return destination
