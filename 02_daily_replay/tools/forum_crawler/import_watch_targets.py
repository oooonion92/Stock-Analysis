from __future__ import annotations

import argparse
import csv
from pathlib import Path

from forum_db import connect, get_site, upsert_target


REQUIRED_COLUMNS = {"site", "name", "user_id"}
VALID_TARGET_TYPES = {"replies", "topics", "posts", "feed", "both"}
VALID_STYLES = {"短线", "趋势", "混合", "未知"}


def as_bool(value: str, default: bool = True) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "on", "启用", "是"}


def as_int(value: str, default: int) -> int:
    text = (value or "").strip()
    if not text:
        return default
    return int(text)


def import_csv(path: Path, dry_run: bool = False) -> tuple[int, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise SystemExit("CSV 缺少表头。")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise SystemExit(f"CSV 缺少必要列：{', '.join(sorted(missing))}")

        rows = list(reader)

    imported = 0
    skipped = 0
    with connect() as conn:
        for index, row in enumerate(rows, 2):
            site = (row.get("site") or "").strip()
            name = (row.get("name") or "").strip()
            user_id = (row.get("user_id") or "").strip()
            if not site or not name or not user_id:
                print(f"[SKIP] 第 {index} 行缺少 site/name/user_id")
                skipped += 1
                continue

            try:
                get_site(conn, site)
            except SystemExit:
                print(f"[SKIP] 第 {index} 行站点未登记：{site}")
                skipped += 1
                continue

            target_type = (row.get("target_type") or "replies").strip() or "replies"
            if target_type not in VALID_TARGET_TYPES:
                print(f"[SKIP] 第 {index} 行 target_type 无效：{target_type}")
                skipped += 1
                continue

            style = (row.get("style") or "未知").strip() or "未知"
            if style not in VALID_STYLES:
                print(f"[SKIP] 第 {index} 行 style 无效：{style}，请填：短线 / 趋势 / 混合 / 未知")
                skipped += 1
                continue

            pages = as_int(row.get("pages", ""), 3)
            enabled = as_bool(row.get("enabled", ""), True)
            profile_url = (row.get("profile_url") or "").strip()
            notes = (row.get("notes") or "").strip()

            if dry_run:
                print(f"[DRY] {site} / {name} user_id={user_id} type={target_type} style={style} pages={pages}")
            else:
                target_id = upsert_target(
                    conn,
                    site_name=site,
                    display_name=name,
                    external_user_id=user_id,
                    profile_url=profile_url,
                    target_type=target_type,
                    style=style,
                    enabled=enabled,
                    crawl_pages=pages,
                    notes=notes,
                )
                print(f"[OK] {site} / {name} user_id={user_id} id={target_id}")
            imported += 1

    return imported, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="从 CSV 批量导入高手跟踪目标。")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="只检查，不写入数据库。")
    args = parser.parse_args()

    imported, skipped = import_csv(args.csv_path, dry_run=args.dry_run)
    action = "检查" if args.dry_run else "导入"
    print(f"{action}完成：有效 {imported} 行，跳过 {skipped} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
