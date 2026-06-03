from __future__ import annotations

from pathlib import Path

from geonode_spider.models.place import DmfwPlaceRecord
from geonode_spider.storage.sqlite import SQLitePlaceRepository


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
            ),
        ]
    )

    stored = repository.list_places()

    assert len(stored) == 1
    assert stored[0].source_id == "abc123"
    assert stored[0].keyword == "村"
    assert stored[0].partition_code == "3501"
