from __future__ import annotations

import json
from pathlib import Path

from geonode_spider.exporters.base import BaseExporter, TabularRecord


class JsonExporter(BaseExporter):
    format_name = "json"

    def export(self, records: list[TabularRecord], destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = [record.to_dict() for record in records]
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination
