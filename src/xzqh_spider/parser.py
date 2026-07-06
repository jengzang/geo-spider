from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from xzqh_spider.models import Division, parse_level

if TYPE_CHECKING:
    from bs4.element import Tag

CODE_PATTERN = re.compile(r"(\d{9})\.html$")


def parse_page(html: str, url: str) -> tuple[Division, list[dict[str, str]]]:
    """Parse a division page. Returns (self, children).

    Each child dict: {"code": "110101001", "name": "东华门街道", "status": "正常"}
    """
    soup = BeautifulSoup(html, "html.parser")

    name = _text_after(soup, "地区名称：")
    short_code = _text_after(soup, "区划代码：")
    code_12 = _text_after(soup, "统计用12位区划代码：")
    if not code_12:
        code_12 = _text_after(soup, "统计用12位区划代码:")
    level_text = _text_after(soup, "地区级别：")
    status = _text_after(soup, "状态：")
    full_name = _text_after(soup, "全称：")

    code_12 = _normalize_code(code_12)
    short_code = _normalize_short_code(short_code) or code_12[:6]

    division = Division(
        code=code_12,
        name=name,
        short_code=short_code,
        parent_code="",  # filled by caller
        level=parse_level(level_text),
        level_text=level_text,
        full_name=full_name or name,
        status=status or "正常",
        source_url=url,
    )

    children = _parse_subordinate_table(soup)
    return division, children


def _text_after(soup: BeautifulSoup, label: str) -> str:
    for tag in soup.find_all(string=lambda t: t and label in t):
        text = tag.strip()
        if text.startswith(label):
            return text[len(label):].strip()
    # Fallback: substring match
    for tag in soup.find_all(string=lambda t: t and label in t):
        parent = tag.parent
        if parent is None:
            continue
        text = parent.get_text(strip=True)
        if label in text:
            value = text.split(label, 1)[-1].strip()
            return value
    return ""


def _normalize_code(raw: str) -> str:
    if not raw:
        return ""
    code = raw.strip()
    if not code.isdigit():
        return code
    # Ensure 12-digit format
    if len(code) == 6:
        return code + "000000"
    if len(code) == 9:
        return code + "000"
    return code


def _normalize_short_code(raw: str) -> str:
    """Keep the short/display code as-is (typically 6 or 9 digits)."""
    if not raw:
        return ""
    return raw.strip()


def _parse_subordinate_table(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract children from the 【下辖行政区划】 table."""
    anchor = soup.find(string=lambda t: t and "下辖行政区划" in t)
    if not anchor:
        return []

    table = anchor.find_next("table")
    if table is None:
        return []

    children: list[dict[str, str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        if not link:
            continue
        name = link.get_text(strip=True)
        href = link.get("href", "")
        code = _extract_code_from_url(href)
        if not code:
            continue
        status_text = cells[-1].get_text(strip=True)
        children.append({"code": _url_code_to_12(code), "name": name, "status": status_text})
    return children


def _extract_code_from_url(href: str) -> str:
    m = CODE_PATTERN.search(href)
    if m:
        return m.group(1)
    return ""


def _url_code_to_12(code_9: str) -> str:
    """Pad a 9-digit URL code to 12-digit statistical code."""
    return code_9 + "000" if len(code_9) == 9 else code_9


def extract_sibling_codes(html: str) -> list[str]:
    """Extract sibling division codes from the 【同级行政区划】 table."""
    soup = BeautifulSoup(html, "html.parser")
    anchor = soup.find(string=lambda t: t and "同级行政区划" in t)
    if not anchor:
        return []

    table = anchor.find_next("table")
    if table is None:
        return []

    codes: list[str] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        if not link:
            continue
        code = _extract_code_from_url(link.get("href", ""))
        if code:
            codes.append(_url_code_to_12(code))
    return codes
