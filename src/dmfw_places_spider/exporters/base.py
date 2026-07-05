from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol


class TabularRecord(Protocol):
    def to_dict(self) -> dict[str, object]:
        ...


class BaseExporter(ABC):
    format_name: str

    @abstractmethod
    def export(self, records: list[TabularRecord], destination: Path) -> Path:
        raise NotImplementedError
