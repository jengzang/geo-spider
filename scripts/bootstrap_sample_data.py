from __future__ import annotations

import sys

from dmfw_places_spider.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["run-pipeline", "--source", "mock", "--export", "all", *sys.argv[1:]]))
