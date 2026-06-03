from __future__ import annotations

import sys

from geonode_spider.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["run-dmfw-chars", *sys.argv[1:]]))
