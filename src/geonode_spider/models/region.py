from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal


RegionLevel = Literal["province", "city", "district", "town"]


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class RegionNode:
    code: str
    name: str
    full_name: str
    level: RegionLevel
    parent_code: str | None
    province_code: str | None
    city_code: str | None
    district_code: str | None
    town_code: str | None
    longitude: float | None
    latitude: float | None
    source_name: str
    source_url: str
    version: str
    captured_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "RegionNode":
        return cls(
            code=str(row["code"]),
            name=str(row["name"]),
            full_name=str(row["full_name"]),
            level=str(row["level"]),  # type: ignore[arg-type]
            parent_code=row["parent_code"] if row["parent_code"] is None else str(row["parent_code"]),
            province_code=row["province_code"] if row["province_code"] is None else str(row["province_code"]),
            city_code=row["city_code"] if row["city_code"] is None else str(row["city_code"]),
            district_code=row["district_code"] if row["district_code"] is None else str(row["district_code"]),
            town_code=row["town_code"] if row["town_code"] is None else str(row["town_code"]),
            longitude=row["longitude"] if row["longitude"] is None else float(row["longitude"]),
            latitude=row["latitude"] if row["latitude"] is None else float(row["latitude"]),
            source_name=str(row["source_name"]),
            source_url=str(row["source_url"]),
            version=str(row["version"]),
            captured_at=str(row["captured_at"]),
            updated_at=str(row["updated_at"]),
        )


@dataclass(slots=True)
class CrawlRunRecord:
    run_id: str
    source_name: str
    status: str
    item_count: int
    started_at: str
    finished_at: str
    error_message: str = ""


@dataclass(slots=True)
class PipelineResult:
    run_id: str
    region_count: int
    source_name: str
    exported_files: dict[str, str]
