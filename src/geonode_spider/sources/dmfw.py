from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from geonode_spider.models.place import DmfwDivision, DmfwPlaceRecord


class DmfwClientProtocol(Protocol):
    def list_divisions(self, code: str) -> list[DmfwDivision]:
        ...

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
        ...


class DmfwProgressProtocol(Protocol):
    def is_completed(self, keyword: str, code: str) -> bool:
        ...

    def mark_completed(self, keyword: str, code: str) -> None:
        ...


@dataclass(slots=True)
class DmfwCollector:
    client: DmfwClientProtocol
    root_divisions: list[DmfwDivision] | None = None
    partition_threshold: int = 3000
    page_size: int = 100
    place_type_code: str = ""
    search_type: str = "模糊"

    def collect_for_chars(
        self,
        chars: str,
        *,
        progress_tracker: DmfwProgressProtocol | None = None,
    ) -> list[DmfwPlaceRecord]:
        unique_chars = _normalize_chars(chars)
        root_divisions = self.root_divisions or self.client.list_divisions("0")
        deduped: dict[str, DmfwPlaceRecord] = {}

        for char in unique_chars:
            for division in root_divisions:
                for place in self._collect_partition(
                    keyword=char,
                    code=division.code,
                    progress_tracker=progress_tracker,
                ):
                    deduped.setdefault(place.source_id, place)

        return list(deduped.values())

    def _collect_partition(
        self,
        *,
        keyword: str,
        code: str,
        progress_tracker: DmfwProgressProtocol | None = None,
    ) -> list[DmfwPlaceRecord]:
        if progress_tracker is not None and progress_tracker.is_completed(keyword, code):
            return []

        first_page = self.client.search_places(
            keyword=keyword,
            code=code,
            page=1,
            size=self.page_size,
            place_type_code=self.place_type_code,
            search_type=self.search_type,
        )
        total = int(first_page.get("total", 0))

        if total > self.partition_threshold:
            children = self.client.list_divisions(code)
            if children:
                records: list[DmfwPlaceRecord] = []
                for child in children:
                    records.extend(
                        self._collect_partition(
                            keyword=keyword,
                            code=child.code,
                            progress_tracker=progress_tracker,
                        )
                    )
                if progress_tracker is not None:
                    progress_tracker.mark_completed(keyword, code)
                return records

        records = self._normalize_records(first_page.get("records", []), keyword=keyword, partition_code=code)
        if total <= len(records):
            return records

        total_pages = max(1, math.ceil(total / self.page_size))
        for page in range(2, total_pages + 1):
            payload = self.client.search_places(
                keyword=keyword,
                code=code,
                page=page,
                size=self.page_size,
                place_type_code=self.place_type_code,
                search_type=self.search_type,
            )
            records.extend(self._normalize_records(payload.get("records", []), keyword=keyword, partition_code=code))
        if progress_tracker is not None:
            progress_tracker.mark_completed(keyword, code)
        return records

    def _normalize_records(
        self,
        records: object,
        *,
        keyword: str,
        partition_code: str,
    ) -> list[DmfwPlaceRecord]:
        normalized: list[DmfwPlaceRecord] = []
        if not isinstance(records, list):
            return normalized
        for record in records:
            if isinstance(record, DmfwPlaceRecord):
                normalized.append(record)
                continue
            if isinstance(record, dict):
                normalized.append(
                    DmfwPlaceRecord.from_api_record(
                        record,
                        keyword=keyword,
                        partition_code=partition_code,
                        source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
                    )
                )
        return normalized


def _normalize_chars(raw_chars: str) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for char in raw_chars:
        if char in {" ", "\n", "\t", ",", "，", "、", ";", "；"}:
            continue
        if char not in seen:
            normalized.append(char)
            seen.add(char)
    return normalized
