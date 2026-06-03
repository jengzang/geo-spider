from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from geonode_spider.models.region import utc_now_iso


@dataclass(slots=True)
class DmfwDivision:
    code: str
    name: str
    parent_code: str
    level: str


@dataclass(slots=True)
class DmfwPlaceRecord:
    source_id: str
    place_code: str
    standard_name: str
    place_type: str
    place_type_code: str
    province_name: str
    city_name: str | None
    area_name: str | None
    area_code: str | None
    longitude: float | None
    latitude: float | None
    keyword: str
    partition_code: str
    source_url: str
    source_name: str = "dmfw"
    roman_alphabet_spelling: str = ""
    ethnic_minorities_writing: str = ""
    raw_payload_json: str = ""
    captured_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_api_record(
        cls,
        record: dict[str, object],
        *,
        keyword: str,
        partition_code: str,
        source_url: str,
    ) -> "DmfwPlaceRecord":
        longitude, latitude = _extract_coordinates(record.get("gdm"))
        return cls(
            source_id=str(record["id"]),
            place_code=str(record.get("place_code", "")),
            standard_name=str(record.get("standard_name", "")),
            place_type=str(record.get("place_type", "")),
            place_type_code=str(record.get("place_type_code", "")),
            province_name=str(record.get("province_name", "")),
            city_name=_optional_str(record.get("city_name")),
            area_name=_optional_str(record.get("area_name")),
            area_code=_optional_str(record.get("area")),
            longitude=longitude,
            latitude=latitude,
            keyword=keyword,
            partition_code=partition_code,
            source_url=source_url,
            roman_alphabet_spelling=str(record.get("roman_alphabet_spelling", "")),
            ethnic_minorities_writing=str(record.get("ethnic_minorities_writing", "")),
            raw_payload_json=json.dumps(record, ensure_ascii=False, sort_keys=True),
        )

    @classmethod
    def from_row(cls, row: dict[str, object]) -> "DmfwPlaceRecord":
        return cls(
            source_id=str(row["source_id"]),
            place_code=str(row["place_code"]),
            standard_name=str(row["standard_name"]),
            place_type=str(row["place_type"]),
            place_type_code=str(row["place_type_code"]),
            province_name=str(row["province_name"]),
            city_name=_optional_str(row["city_name"]),
            area_name=_optional_str(row["area_name"]),
            area_code=_optional_str(row["area_code"]),
            longitude=row["longitude"] if row["longitude"] is None else float(row["longitude"]),
            latitude=row["latitude"] if row["latitude"] is None else float(row["latitude"]),
            keyword=str(row["keyword"]),
            partition_code=str(row["partition_code"]),
            source_url=str(row["source_url"]),
            source_name=str(row["source_name"]),
            roman_alphabet_spelling=str(row["roman_alphabet_spelling"]),
            ethnic_minorities_writing=str(row["ethnic_minorities_writing"]),
            raw_payload_json=str(row["raw_payload_json"]),
            captured_at=str(row["captured_at"]),
            updated_at=str(row["updated_at"]),
        )


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _extract_coordinates(gdm: object) -> tuple[float | None, float | None]:
    if not isinstance(gdm, dict):
        return None, None
    coordinates = gdm.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return None, None
    first = coordinates[0]
    if not isinstance(first, list) or len(first) < 2:
        return None, None
    try:
        return float(first[0]), float(first[1])
    except (TypeError, ValueError):
        return None, None
