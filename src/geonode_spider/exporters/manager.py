from __future__ import annotations

from pathlib import Path

from geonode_spider.exporters.csv_exporter import CsvExporter
from geonode_spider.exporters.excel_exporter import ExcelExporter
from geonode_spider.exporters.json_exporter import JsonExporter
from geonode_spider.exporters.sqlite_exporter import SqliteExporter
from geonode_spider.models.region import RegionNode


class ExportManager:
    def __init__(self) -> None:
        self._exporters = {
            "json": JsonExporter(),
            "csv": CsvExporter(),
            "xlsx": ExcelExporter(),
            "db": SqliteExporter(),
        }

    def export(self, regions: list[RegionNode], export_dir: Path, formats: list[str]) -> dict[str, str]:
        export_dir.mkdir(parents=True, exist_ok=True)
        requested = self._normalize_formats(formats)
        exported: dict[str, str] = {}
        for format_name in requested:
            exporter = self._exporters[format_name]
            destination = export_dir / f"regions.{format_name}"
            if format_name == "db":
                destination = export_dir / "regions.db"
            path = exporter.export(regions, destination)
            exported[format_name] = str(path)
        return exported

    def _normalize_formats(self, formats: list[str]) -> list[str]:
        if not formats or formats == ["all"]:
            return ["json", "csv", "xlsx", "db"]
        normalized: list[str] = []
        for item in formats:
            if item == "all":
                return ["json", "csv", "xlsx", "db"]
            if item not in self._exporters:
                raise ValueError(f"unsupported export format: {item}")
            normalized.append(item)
        return normalized
