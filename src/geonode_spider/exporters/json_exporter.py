from __future__ import annotations

import json
from pathlib import Path

from geonode_spider.exporters.base import BaseExporter
from geonode_spider.models.region import RegionNode


class JsonExporter(BaseExporter):
    format_name = "json"

    def export(self, regions: list[RegionNode], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = [region.to_dict() for region in regions]
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination
