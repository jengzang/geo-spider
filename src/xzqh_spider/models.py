from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Division:
    code: str           # 12-digit: "110000000000"
    name: str           # "北京市"
    short_code: str     # 6-digit: "110000"
    parent_code: str    # parent 12-digit code, "" for root
    level: str          # province | city | district | town
    level_text: str     # original: "省(自治区、直辖市)"
    full_name: str      # "北京市"
    status: str         # "正常" | "停用"
    source_url: str
    captured_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "short_code": self.short_code,
            "parent_code": self.parent_code,
            "level": self.level,
            "level_text": self.level_text,
            "full_name": self.full_name,
            "status": self.status,
            "source_url": self.source_url,
            "captured_at": self.captured_at,
        }


def parse_level(level_text: str) -> str:
    """Detect admin division level from the page's level text.

    The site uses mixed full-width/half-width parentheses, e.g.:
    省(自治区、直辖市), 市（地区、自治州), 县（市辖区、县级市), 乡、镇（街道办事处）
    """
    text = level_text.strip()
    if text.startswith("省"):
        return "province"
    if text.startswith("市"):
        return "city"
    if text.startswith("县"):
        return "district"
    if text.startswith(("乡", "镇", "街道")):
        return "town"
    return "unknown"


STOP_LEVELS = {"district", "town", "unknown"}
