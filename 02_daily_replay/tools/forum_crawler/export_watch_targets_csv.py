from __future__ import annotations

import argparse
import csv
from pathlib import Path

from forum_db import DATA_DIR, connect


DEFAULT_OUTPUT = DATA_DIR / "watch_targets.csv"


def export_watch_targets(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        rows = list(
            conn.execute(
                """
                SELECT
                    sites.name AS site,
                    watch_targets.display_name AS name,
                    watch_targets.external_user_id AS user_id,
                    watch_targets.target_type,
                    watch_targets.style,
                    watch_targets.crawl_pages AS pages,
                    watch_targets.profile_url,
                    watch_targets.enabled,
                    watch_targets.notes
                FROM watch_targets
                JOIN sites ON sites.id = watch_targets.site_id
                ORDER BY sites.name, watch_targets.display_name
                """
            )
        )

    fieldnames = ["site", "name", "user_id", "target_type", "style", "pages", "profile_url", "enabled", "notes"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row[field] for field in fieldnames})

    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="从数据库导出 Excel 友好的高手跟踪 CSV。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    count = export_watch_targets(args.output)
    print(f"已导出 {count} 个跟踪目标：{args.output}")
    print("编码：UTF-8 with BOM，适合 Windows Excel 直接打开。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
