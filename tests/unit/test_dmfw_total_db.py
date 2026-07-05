from __future__ import annotations

import sqlite3
from pathlib import Path

from dmfw_places_spider.models.place import DmfwPlaceRecord
from dmfw_places_spider.storage.sqlite import SQLiteTotalPlaceRepository


def _record(source_id: str, standard_name: str, place_code: str) -> DmfwPlaceRecord:
    return DmfwPlaceRecord(
        source_id=source_id,
        place_code=place_code,
        standard_name=standard_name,
        place_type="行政村",
        place_type_code="21610",
        province_name="测试省",
        city_name="测试市",
        area_name="测试区",
        area_code="350101",
        longitude=118.1,
        latitude=24.1,
        keyword="村",
        partition_code="35",
        source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
        match_mode="contain",
        geometry_type="multipoint",
        coordinates_json="[[118.1, 24.1]]",
    )


def _multi_record(source_id: str, standard_name: str, place_code: str) -> DmfwPlaceRecord:
    return DmfwPlaceRecord(
        source_id=source_id,
        place_code=place_code,
        standard_name=standard_name,
        place_type="街路巷",
        place_type_code="21800",
        province_name="测试省",
        city_name="测试市",
        area_name="测试区",
        area_code="350101",
        longitude=None,
        latitude=None,
        keyword="村",
        partition_code="35",
        source_url="https://dmfw.mca.gov.cn/9095/stname/listPub",
        match_mode="contain",
        geometry_type="linestring",
        coordinates_json="[[118.1, 24.1], [118.2, 24.2], [118.3, 24.3]]",
    )


def test_upsert_places_append_mode_deduplicates_by_source_id(tmp_path: Path) -> None:
    db_path = tmp_path / "dmfw_total.db"
    repository = SQLiteTotalPlaceRepository(db_path)
    repository.initialize()

    repository.upsert_places([
        _record("sid-1", "东村", "35010100121610000001"),
        _record("sid-2", "西村", "35010100121610000002"),
    ])
    assert repository.count_places() == 2
    assert repository.count_single_places() == 2
    assert repository.count_multi_places() == 0

    repository.upsert_places([
        _record("sid-2", "西村", "35010100121610000002"),
        _record("sid-3", "南村", "35010100121610000003"),
    ])
    assert repository.count_places() == 3

    names = [row.standard_name for row in repository.list_places()]
    assert names.count("西村") == 1


def test_total_repository_omits_run_only_fields_and_uses_split_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "dmfw_total.db"
    repository = SQLiteTotalPlaceRepository(db_path)
    repository.initialize()
    repository.upsert_places([_record("sid-1", "东村", "35010100121610000001")])

    with sqlite3.connect(db_path) as conn:
        single_columns = [row[1] for row in conn.execute("PRAGMA table_info(dmfw_places_single)").fetchall()]
        multi_columns = [row[1] for row in conn.execute("PRAGMA table_info(dmfw_places_multi)").fetchall()]

    assert "keyword" not in single_columns
    assert "partition_code" not in single_columns
    assert "source_url" not in single_columns
    assert "source_name" not in single_columns
    assert "roman_alphabet_spelling" not in single_columns
    assert "ethnic_minorities_writing" not in single_columns
    assert "raw_payload_json" not in single_columns
    assert "match_mode" not in single_columns
    assert "fetched_at_utc" not in single_columns
    assert "coordinates_json" not in single_columns

    assert "longitude" not in multi_columns
    assert "latitude" not in multi_columns
    assert "geometry_type" in multi_columns
    assert "coordinates_json" in multi_columns


def test_total_repository_routes_multi_coordinate_records_to_multi_table(tmp_path: Path) -> None:
    db_path = tmp_path / "dmfw_total.db"
    repository = SQLiteTotalPlaceRepository(db_path)
    repository.initialize()

    repository.upsert_places([
        _record("sid-1", "东村", "35010100121610000001"),
        _multi_record("sid-2", "龙村街", "35010100121800000001"),
    ])

    assert repository.count_single_places() == 1
    assert repository.count_multi_places() == 1
    assert repository.count_places() == 2

    stored = repository.list_places()
    multi = next(row for row in stored if row.source_id == "sid-2")
    assert multi.geometry_type == "linestring"
    assert multi.coordinates == [[118.1, 24.1], [118.2, 24.2], [118.3, 24.3]]
    assert multi.longitude is None
    assert multi.latitude is None
