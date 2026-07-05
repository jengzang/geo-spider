from __future__ import annotations

from pathlib import Path

from dmfw_places_spider.models.place import DmfwPlaceRecord
from dmfw_places_spider.storage.sqlite import SQLitePlaceRepository


def test_place_repository_upserts_and_deduplicates_source_ids(tmp_path: Path) -> None:
    repository = SQLitePlaceRepository(tmp_path / "places.db")
    repository.initialize()

    repository.upsert_places(
        [
            DmfwPlaceRecord(
                source_id="abc123",
                place_code="35010510021400000000",
                standard_name="马尾区",
                place_type="县级行政区",
                place_type_code="21400",
                province_name="福建省",
                city_name="福州市",
                area_name="马尾区",
                area_code="350105999",
                longitude=119.4502181,
                latitude=25.991718,
                keyword="尾",
                partition_code="35",
                source_url="https://dmfw.mca.gov.cn/stname/listPub",
                match_mode="contain",
                fetched_at_utc="2026-06-03T00:00:00+00:00",
                geometry_type="multipoint",
                coordinates_json="[[119.4502181, 25.991718]]",
            ),
            DmfwPlaceRecord(
                source_id="abc123",
                place_code="35010510021400000000",
                standard_name="马尾区",
                place_type="县级行政区",
                place_type_code="21400",
                province_name="福建省",
                city_name="福州市",
                area_name="马尾区",
                area_code="350105999",
                longitude=119.4502181,
                latitude=25.991718,
                keyword="村",
                partition_code="3501",
                source_url="https://dmfw.mca.gov.cn/stname/listPub",
                match_mode="exact",
                fetched_at_utc="2026-06-03T00:01:00+00:00",
                geometry_type="multipoint",
                coordinates_json="[[119.4502181, 25.991718]]",
            ),
        ]
    )

    stored = repository.list_places()

    assert len(stored) == 1
    assert stored[0].source_id == "abc123"
    assert stored[0].keyword == "村"
    assert stored[0].partition_code == "3501"
    assert stored[0].match_mode == "exact"
    assert stored[0].fetched_at_utc == "2026-06-03T00:01:00+00:00"


def test_place_record_parses_multi_coordinates_without_primary_lon_lat() -> None:
    record = DmfwPlaceRecord.from_api_record(
        {
            "id": "multi-1",
            "place_code": "35010100121800000001",
            "standard_name": "龙村街",
            "place_type": "街路巷",
            "place_type_code": "21800",
            "province_name": "福建省",
            "city_name": "福州市",
            "area_name": "鼓楼区",
            "area": "350102001",
            "roman_alphabet_spelling": "Longcunjie",
            "ethnic_minorities_writing": "",
            "gdm": {
                "type": "linestring",
                "coordinates": [
                    [118.1, 24.1],
                    [118.2, 24.2],
                    [118.3, 24.3],
                ],
            },
        },
        keyword="村",
        partition_code="35",
        source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
        match_mode="contain",
        fetched_at_utc="2026-06-05T00:00:00+00:00",
    )

    assert record.geometry_type == "linestring"
    assert record.coordinates == [[118.1, 24.1], [118.2, 24.2], [118.3, 24.3]]
    assert record.longitude is None
    assert record.latitude is None
