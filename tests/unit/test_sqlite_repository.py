from __future__ import annotations

from pathlib import Path

from geonode_spider.models.region import RegionNode
from geonode_spider.storage.sqlite import SQLiteRegionRepository


def test_repository_initializes_schema_and_roundtrips_regions(tmp_path: Path) -> None:
    repository = SQLiteRegionRepository(tmp_path / "regions.db")
    repository.initialize()

    repository.upsert_regions(
        [
            RegionNode(
                code="110000",
                name="北京市",
                full_name="北京市",
                level="province",
                parent_code=None,
                province_code="110000",
                city_code=None,
                district_code=None,
                town_code=None,
                longitude=116.4074,
                latitude=39.9042,
                source_name="mock",
                source_url="https://example.com/mock",
                version="2026-04",
            ),
            RegionNode(
                code="110101",
                name="东城区",
                full_name="北京市东城区",
                level="district",
                parent_code="110000",
                province_code="110000",
                city_code="110000",
                district_code="110101",
                town_code=None,
                longitude=None,
                latitude=None,
                source_name="mock",
                source_url="https://example.com/mock",
                version="2026-04",
            ),
        ]
    )

    stored = repository.list_regions()

    assert [region.code for region in stored] == ["110000", "110101"]
    assert stored[0].name == "北京市"
    assert stored[1].parent_code == "110000"
    assert stored[1].longitude is None
