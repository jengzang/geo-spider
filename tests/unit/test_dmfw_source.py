from __future__ import annotations

from geonode_spider.models.place import DmfwDivision, DmfwPlaceRecord
from geonode_spider.sources.dmfw import DmfwCollector


class FakeDmfwClient:
    def __init__(self) -> None:
        self.list_division_calls: list[str] = []
        self.search_calls: list[tuple[str, str, int, int]] = []
        self.root_divisions = [
            DmfwDivision(code="35", name="福建省", parent_code="0", level="province"),
            DmfwDivision(code="44", name="广东省", parent_code="0", level="province"),
        ]
        self.children = {
            "35": [
                DmfwDivision(code="3501", name="福州市", parent_code="35", level="city"),
                DmfwDivision(code="3502", name="厦门市", parent_code="35", level="city"),
            ],
            "44": [],
        }
        self.responses = {
            ("尾", "35", 1): {
                "total": 3100,
                "records": [],
            },
            ("尾", "3501", 1): {
                "total": 2,
                "records": [
                    self._record("p1", "尾村", "3501"),
                    self._record("shared", "溪尾", "3501"),
                ],
            },
            ("尾", "3502", 1): {
                "total": 1,
                "records": [
                    self._record("shared", "溪尾", "3502"),
                ],
            },
            ("尾", "44", 1): {
                "total": 1,
                "records": [
                    self._record("p2", "山尾", "44"),
                ],
            },
            ("村", "35", 1): {
                "total": 1,
                "records": [
                    self._record("p3", "东村", "35"),
                ],
            },
            ("村", "44", 1): {
                "total": 0,
                "records": [],
            },
        }

    def list_divisions(self, code: str) -> list[DmfwDivision]:
        self.list_division_calls.append(code)
        if code == "0":
            return self.root_divisions
        return self.children.get(code, [])

    def search_places(
        self,
        *,
        keyword: str,
        code: str,
        page: int = 1,
        size: int = 100,
        place_type_code: str = "",
        year: int = 0,
        search_type: str = "模糊",
    ) -> dict[str, object]:
        _ = (size, place_type_code, year, search_type)
        self.search_calls.append((keyword, code, page, size))
        return self.responses[(keyword, code, page)]

    def _record(self, source_id: str, name: str, code: str) -> DmfwPlaceRecord:
        return DmfwPlaceRecord(
            source_id=source_id,
            place_code=f"{code}000000000000000000",
            standard_name=name,
            place_type="农村居民点",
            place_type_code="22200",
            province_name="测试省",
            city_name="测试市",
            area_name="测试区",
            area_code=code,
            longitude=118.1,
            latitude=24.1,
            keyword="尾",
            partition_code=code,
            source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
            match_mode="contain",
        )


def test_collector_recursively_partitions_and_deduplicates_places() -> None:
    client = FakeDmfwClient()
    collector = DmfwCollector(
        client=client,
        root_divisions=client.root_divisions,
        partition_threshold=3000,
        page_size=100,
    )

    results = collector.collect_for_chars("尾村")

    assert {place.standard_name for place in results} == {"东村", "山尾", "尾村", "溪尾"}
    assert [place.source_id for place in results].count("shared") == 1
    assert client.list_division_calls == ["35"]
