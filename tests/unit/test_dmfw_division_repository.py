from __future__ import annotations

from pathlib import Path

from dmfw_places_spider.models.place import DmfwDivision
from dmfw_places_spider.storage.sqlite import SQLiteDivisionRepository


def test_division_repository_upserts_and_lists_root_divisions(tmp_path: Path) -> None:
    repository = SQLiteDivisionRepository(tmp_path / "places.db")
    repository.initialize()

    repository.upsert_divisions(
        [
            DmfwDivision(code="35", name="福建省", parent_code="0", level="province"),
            DmfwDivision(code="44", name="广东省", parent_code="0", level="province"),
            DmfwDivision(code="3501", name="福州市", parent_code="35", level="city"),
        ]
    )

    roots = repository.list_divisions(parent_code="0")
    children = repository.list_divisions(parent_code="35")

    assert [division.code for division in roots] == ["35", "44"]
    assert [division.name for division in roots] == ["福建省", "广东省"]
    assert [division.code for division in children] == ["3501"]
