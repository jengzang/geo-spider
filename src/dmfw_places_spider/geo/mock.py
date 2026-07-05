from __future__ import annotations

from dmfw_places_spider.geo.base import GeoCoder
from dmfw_places_spider.models.region import RegionNode


MOCK_COORDINATES = {
    "110100": (116.4075, 39.9043),
    "110101": (116.4180, 39.9288),
    "110101001": (116.4173, 39.9170),
}


class MockGeoCoder(GeoCoder):
    def enrich(self, regions: list[RegionNode]) -> list[RegionNode]:
        enriched: list[RegionNode] = []
        for region in regions:
            if region.longitude is None or region.latitude is None:
                coordinates = MOCK_COORDINATES.get(region.code)
                if coordinates is not None:
                    region.longitude, region.latitude = coordinates
            enriched.append(region)
        return enriched
