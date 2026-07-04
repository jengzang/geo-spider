"""ID 文件流式读取 / 去重。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import logging

logger = logging.getLogger(__name__)


def iter_ids_from_file(path: str) -> Iterator[str]:
    """流式读取每行一个 ID 的文本文件，跳过空行，去掉前后空白。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"ID 文件不存在: {path}")

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                yield stripped


def iter_ids_from_files(paths: list[str]) -> Iterator[str]:
    """多文件流式读取，文件间不去重。"""
    for path in paths:
        yield from iter_ids_from_file(path)


def count_lines_in_file(path: str) -> int:
    """快速统计文件行数。"""
    count = 0
    with open(path, "rb") as f:
        for _ in f:
            count += 1
    return count
