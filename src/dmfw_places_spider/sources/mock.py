from __future__ import annotations

from dmfw_places_spider.models.region import RegionNode
from dmfw_places_spider.sources.base import AdministrativeSource


class MockAdministrativeSource(AdministrativeSource):
    name = "mock"

    def fetch_regions(self) -> list[RegionNode]:
        return [
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
                source_name=self.name,
                source_url="https://example.com/mock",
                version="2026-04",
            ),
            RegionNode(
                code="110100",
                name="市辖区",
                full_name="北京市市辖区",
                level="city",
                parent_code="110000",
                province_code="110000",
                city_code="110100",
                district_code=None,
                town_code=None,
                longitude=None,
                latitude=None,
                source_name=self.name,
                source_url="https://example.com/mock",
                version="2026-04",
            ),
            RegionNode(
                code="110101",
                name="东城区",
                full_name="北京市东城区",
                level="district",
                parent_code="110100",
                province_code="110000",
                city_code="110100",
                district_code="110101",
                town_code=None,
                longitude=None,
                latitude=None,
                source_name=self.name,
                source_url="https://example.com/mock",
                version="2026-04",
            ),
            RegionNode(
                code="110101001",
                name="东华门街道",
                full_name="北京市东城区东华门街道",
                level="town",
                parent_code="110101",
                province_code="110000",
                city_code="110100",
                district_code="110101",
                town_code="110101001",
                longitude=None,
                latitude=None,
                source_name=self.name,
                source_url="https://example.com/mock",
                version="2026-04",
            ),
        ]
