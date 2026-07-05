from __future__ import annotations

import json
from pathlib import Path

from dmfw_places_spider.services.dmfw import DmfwProgressTracker


def test_progress_tracker_persists_and_resumes_completed_partitions(tmp_path: Path) -> None:
    progress_path = tmp_path / "dmfw.progress.json"

    tracker = DmfwProgressTracker(path=progress_path, chars="尾村", resume=False)
    tracker.mark_completed("尾", "35")

    resumed = DmfwProgressTracker(path=progress_path, chars="尾村", resume=True)

    assert resumed.is_completed("尾", "35") is True
    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["completed"] == ["尾|35"]


def test_progress_tracker_does_not_duplicate_completed_tokens(tmp_path: Path) -> None:
    progress_path = tmp_path / "dmfw.progress.json"

    tracker = DmfwProgressTracker(path=progress_path, chars="尾村", resume=False)
    tracker.mark_completed("尾", "35")
    tracker.mark_completed("尾", "35")

    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["completed"] == ["尾|35"]
