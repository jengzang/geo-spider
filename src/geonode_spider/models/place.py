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
    source_name: str = "dmfw"
    captured_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
    match_mode: str = "contain"
    fetched_at_utc: str = field(default_factory=utc_now_iso)
    captured_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    geometry_type: str = ""
    coordinates_json: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_total_single_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "place_code": self.place_code,
            "standard_name": self.standard_name,
            "place_type": self.place_type,
            "place_type_code": self.place_type_code,
            "province_name": self.province_name,
            "city_name": self.city_name,
            "area_name": self.area_name,
            "area_code": self.area_code,
            "longitude": self.longitude,
            "latitude": self.latitude,
            "captured_at": self.captured_at,
            "updated_at": self.updated_at,
        }

    def to_total_multi_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "place_code": self.place_code,
            "standard_name": self.standard_name,
            "place_type": self.place_type,
            "place_type_code": self.place_type_code,
            "province_name": self.province_name,
            "city_name": self.city_name,
            "area_name": self.area_name,
            "area_code": self.area_code,
            "geometry_type": self.geometry_type,
            "coordinates_json": self.coordinates_json,
            "captured_at": self.captured_at,
            "updated_at": self.updated_at,
        }

    def has_single_coordinate(self) -> bool:
        coordinates = self.coordinates
        return len(coordinates) == 1 and len(coordinates[0]) >= 2

    def has_multi_coordinates(self) -> bool:
        return len(self.coordinates) > 1

    @property
    def coordinates(self) -> list[list[float]]:
        if not self.coordinates_json:
            return []
        try:
            payload = json.loads(self.coordinates_json)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        normalized: list[list[float]] = []
        for item in payload:
            if not isinstance(item, list) or len(item) < 2:
                continue
            try:
                normalized.append([float(item[0]), float(item[1])])
            except (TypeError, ValueError):
                continue
        return normalized

    @classmethod
    def from_api_record(
        cls,
        record: dict[str, object],
        *,
        keyword: str,
        partition_code: str,
        source_url: str,
        match_mode: str,
        fetched_at_utc: str,
    ) -> "DmfwPlaceRecord":
        geometry_type, coordinates = _extract_geometry(record.get("gdm"))
        longitude, latitude = _extract_primary_point(coordinates)
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
            match_mode=match_mode,
            fetched_at_utc=fetched_at_utc,
            geometry_type=geometry_type,
            coordinates_json=json.dumps(coordinates, ensure_ascii=False),
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
            match_mode=str(row.get("match_mode", "contain")),
            fetched_at_utc=str(row.get("fetched_at_utc", row["captured_at"])),
            captured_at=str(row["captured_at"]),
            updated_at=str(row["updated_at"]),
            geometry_type=str(row.get("geometry_type", "")),
            coordinates_json=str(row.get("coordinates_json", "")),
        )


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _extract_geometry(gdm: object) -> tuple[str, list[list[float]]]:
    if not isinstance(gdm, dict):
        return "", []
    geometry_type = str(gdm.get("type", ""))
    coordinates = gdm.get("coordinates")
    if not isinstance(coordinates, list):
        return geometry_type, []
    normalized: list[list[float]] = []
    for item in coordinates:
        if not isinstance(item, list) or len(item) < 2:
            continue
        try:
            normalized.append([float(item[0]), float(item[1])])
        except (TypeError, ValueError):
            continue
    return geometry_type, normalized


def _extract_primary_point(coordinates: list[list[float]]) -> tuple[float | None, float | None]:
    if len(coordinates) != 1:
        return None, None
    first = coordinates[0]
    if len(first) < 2:
        return None, None
    return float(first[0]), float(first[1])
