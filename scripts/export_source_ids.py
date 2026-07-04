"""导出 dmfw_places_total.db 中所有 source_id 到 data/id/ 目录，只读不写。"""
from __future__ import annotations

import os
import sqlite3

DB_PATH = "data/processed/dmfw_places_total.db"
OUT_DIR = "data/id"
BATCH_SIZE = 100_000

TABLES = ["dmfw_places_single", "dmfw_places_multi"]


def export_table(db_path: str, table: str, out_path: str) -> int:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    try:
        with open(out_path, "w") as f:
            cursor = conn.execute(f"SELECT source_id FROM {table}")
            count = 0
            while True:
                rows = cursor.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                for (source_id,) in rows:
                    f.write(f"{source_id}\n")
                count += len(rows)
                if count % 1_000_000 == 0:
                    print(f"  {table}: {count:,} 条已导出...")
        return count
    finally:
        conn.close()


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    for table in TABLES:
        out_path = os.path.join(OUT_DIR, f"{table}.txt")
        print(f"导出 {table} -> {out_path}")
        count = export_table(DB_PATH, table, out_path)
        file_size = os.path.getsize(out_path)
        print(f"  完成: {count:,} 条, {file_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
