from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from forum_db import ROOT, connect, get_site, list_targets, posts_for_target


OUTPUT_ROOT = ROOT / "02_daily_replay" / "source_notes" / "crawled_forum_posts"


def slug(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    return cleaned or "unknown"


def render_markdown(rows, site_name: str, target_name: str, user_id: str) -> str:
    lines = [
        f"# {site_name} 作者发言：{target_name}",
        "",
        f"- user_id: `{user_id}`",
        f"- records: {len(rows)}",
        "",
    ]
    for index, row in enumerate(rows, 1):
        lines.extend(
            [
                f"## {index}. {row['title'] or '(无标题)'}",
                "",
                f"- 时间：{row['published_at'] or '未知'}",
                f"- 链接：{row['url']}",
                "",
                row["content"].strip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def sort_key(row) -> tuple[int, str]:
    value = row["published_at"] or ""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return (1, datetime.strptime(value, fmt).isoformat())
        except ValueError:
            continue
    return (0, row["crawled_at"] or "")


def export_target_posts(conn, site, target, output_root: Path, formats: list[str], limit: int | None = None) -> list[Path]:
    rows = sorted(posts_for_target(conn, int(target["id"]), limit=None), key=sort_key, reverse=True)
    if limit:
        rows = rows[:limit]
    out_dir = output_root / site["site_type"] / str(target["style"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{slug(target['display_name'])}_{target['external_user_id']}_posts"
    paths: list[Path] = []

    if "jsonl" in formats:
        out_path = out_dir / f"{stem}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(row["raw_json"] + "\n")
        paths.append(out_path)

    if "md" in formats:
        out_path = out_dir / f"{stem}.md"
        text = render_markdown(rows, site["name"], target["display_name"], target["external_user_id"])
        out_path.write_text(text, encoding="utf-8-sig")
        paths.append(out_path)

    return paths


def export_all_posts(
    output_root: Path = OUTPUT_ROOT,
    site_name: str | None = None,
    formats: list[str] | None = None,
    limit: int | None = None,
) -> list[Path]:
    formats = formats or ["md"]
    paths: list[Path] = []
    with connect() as conn:
        targets = list_targets(conn)
        for target in targets:
            if not target["enabled"]:
                continue
            if site_name and target["site_name"] != site_name:
                continue
            site = get_site(conn, target["site_name"])
            paths.extend(export_target_posts(conn, site, target, output_root, formats, limit=limit))
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="从数据库导出高手发言。")
    parser.add_argument("--site", required=True)
    parser.add_argument("--name", help="指定高手显示名；不填则导出该站点所有启用目标。")
    parser.add_argument("--format", default="md", choices=["md", "jsonl", "both"])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    formats = ["md", "jsonl"] if args.format == "both" else [args.format]

    with connect() as conn:
        site = get_site(conn, args.site)
        if not args.name:
            paths = []
            for target in list_targets(conn):
                if target["site_name"] == args.site and target["enabled"]:
                    paths.extend(export_target_posts(conn, site, target, OUTPUT_ROOT, formats, limit=args.limit))
            print(f"已导出 {len(paths)} 个文件。")
            for path in paths:
                print(path)
            return 0

        target = conn.execute(
            """
            SELECT * FROM watch_targets
            WHERE site_id = ? AND display_name = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(site["id"]), args.name),
        ).fetchone()
        if target is None:
            raise SystemExit(f"跟踪目标不存在：{args.site} / {args.name}")

        paths = export_target_posts(conn, site, target, OUTPUT_ROOT, formats, limit=args.limit)

    print(f"已导出 {len(paths)} 个文件。")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
