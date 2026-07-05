from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from dmfw_places_spider.exporters.base import BaseExporter, TabularRecord


class ExcelExporter(BaseExporter):
    format_name = "xlsx"

    def export(self, records: list[TabularRecord], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "regions"
        rows = [record.to_dict() for record in records]
        if rows:
            headers = list(rows[0].keys())
            sheet.append(headers)
            for row in rows:
                sheet.append([row[header] for header in headers])
        workbook.save(destination)
        return destination
