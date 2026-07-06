from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue
from typing import NamedTuple

import requests

from xzqh_spider.models import STOP_LEVELS, Division, utc_now_iso
from xzqh_spider.parser import extract_sibling_codes, parse_page
from xzqh_spider.repository import XzqhRepository

logger = logging.getLogger(__name__)

BASE_URL = "https://tool.51yww.com/shm/20"
SEED_CODE = "110000000000"
CHECKPOINT_INTERVAL = 100

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Task(NamedTuple):
    code: str
    parent_code: str


def crawl(
    *,
    db_path: str | Path,
    delay: float = 0.0,
    workers: int = 8,
    resume: bool = False,
    checkpoint_path: str | Path | None = None,
    sample_limit: int = 0,
) -> dict:
    repo = XzqhRepository(db_path)
    repo.initialize()

    cp_path = Path(checkpoint_path) if checkpoint_path else Path(db_path).with_suffix(".checkpoint.json")
    completed: set[str] = set()
    if resume and cp_path.exists():
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        completed = set(data.get("completed", []))
        logger.info(f"Resumed from checkpoint: {len(completed)} completed codes")

    # Step 1: discover all provinces
    logger.info("Discovering provinces from seed page...")
    province_codes = _discover_provinces(completed)
    logger.info(f"Discovered {len(province_codes)} provinces")

    # Step 2: concurrent crawl
    queue: Queue[Task] = Queue()
    for code in province_codes:
        if code not in completed:
            queue.put(Task(code, ""))

    lock = threading.Lock()
    page_count = [0]
    start_time = time.monotonic()

    def worker() -> int:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        worker_repo = XzqhRepository(db_path)
        worker_repo.initialize()
        fetched = 0

        while True:
            try:
                task = queue.get(timeout=2)
            except Exception:
                break

            code, parent_code = task.code, task.parent_code

            with lock:
                if sample_limit and page_count[0] >= sample_limit:
                    queue.task_done()
                    continue
                if code in completed:
                    queue.task_done()
                    continue
                completed.add(code)
                cnt = page_count[0] + 1
                page_count[0] = cnt

            url = f"{BASE_URL}/{_code_to_url(code)}.html"

            try:
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                resp.encoding = "utf-8"
            except Exception as exc:
                logger.error(f"[{cnt}] Failed {url}: {exc}")
                queue.task_done()
                continue

            division, children = parse_page(resp.text, url)
            division.parent_code = parent_code
            worker_repo.upsert(division)
            fetched += 1

            child_count = len(children)
            elapsed = time.monotonic() - start_time
            rate = cnt / elapsed if elapsed > 0 else 0
            logger.info(
                f"[{cnt}] {division.name} ({division.level}) "
                f"{child_count} children | {rate:.1f} pg/s | queue: {queue.qsize()}"
            )

            if children:
                if division.level in STOP_LEVELS:
                    child_divs = _children_to_divisions(children, parent_code=code, base_url=BASE_URL)
                    worker_repo.upsert_many(child_divs)
                    fetched += len(child_divs)
                else:
                    for child in children:
                        child_code = child["code"]
                        if child_code:
                            queue.put(Task(child_code, code))

            # Checkpoint
            if cnt % CHECKPOINT_INTERVAL == 0:
                with lock:
                    _save_checkpoint(cp_path, completed)
                counts = worker_repo.count_by_level()
                logger.info(f"  [checkpoint] {counts} | {cnt} pages, {rate:.1f} pg/s")

            if delay > 0:
                time.sleep(delay)
            queue.task_done()

        session.close()
        return fetched

    logger.info(f"Starting {workers} workers, {queue.qsize()} seed tasks in queue")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker) for _ in range(workers)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                logger.error(f"Worker failed: {exc}")

    _save_checkpoint(cp_path, completed)
    counts = repo.count_by_level()
    total = repo.count()
    elapsed = time.monotonic() - start_time
    logger.info(f"Crawl complete: {total} divisions in {elapsed:.0f}s, {counts}")

    return {
        "total": total,
        "by_level": counts,
        "pages_fetched": page_count[0],
        "elapsed_seconds": round(elapsed, 1),
    }


def _discover_provinces(completed: set[str]) -> list[str]:
    url = f"{BASE_URL}/{_code_to_url(SEED_CODE)}.html"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as exc:
        logger.error(f"Failed to fetch seed page {url}: {exc}")
        return [SEED_CODE]

    codes = extract_sibling_codes(resp.text)
    if not codes:
        logger.warning("No provinces found in seed page, using seed code only")
        return [SEED_CODE]
    return codes


def _code_to_url(code: str) -> str:
    return code[:9]


def _children_to_divisions(
    children: list[dict[str, str]],
    parent_code: str,
    base_url: str,
) -> list[Division]:
    divisions: list[Division] = []
    now = utc_now_iso()
    for child in children:
        code = child["code"]
        if len(code) == 12 and code.endswith("000000"):
            short = code[:6]
        else:
            short = code[:9] if len(code) >= 9 else code
        divisions.append(Division(
            code=code,
            name=child["name"],
            short_code=short,
            parent_code=parent_code,
            level="town",
            level_text="",
            full_name=child["name"],
            status=child.get("status", "正常"),
            source_url=f"{base_url}/{_code_to_url(code)}.html",
            captured_at=now,
        ))
    return divisions


def _save_checkpoint(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"completed": sorted(completed)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
