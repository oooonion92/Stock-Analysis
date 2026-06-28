from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "02_daily_replay" / "data" / "forum_watchlist.sqlite"
CLOUD_ROOT = Path(r"D:\OneDrive\Stock\Replies collect")


def date_window(preset: str, start: str = "", end: str = "") -> tuple[str, str, str]:
    today = date.today()
    if preset == "today":
        begin = finish = today
        label = "today"
    elif preset == "weekend":
        days_since_friday = (today.weekday() - 4) % 7
        begin = today - timedelta(days=days_since_friday)
        finish = begin + timedelta(days=2)
        label = "weekend"
    elif preset == "custom" and start and end:
        return start, end, f"{start}_to_{end}"
    else:
        begin = today - timedelta(days=2)
        finish = today
        label = "recent3"
    return begin.isoformat(), finish.isoformat(), label


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_evidence(start_date: str, end_date: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                posts.id,
                posts.url,
                posts.title,
                posts.content,
                posts.published_at,
                posts.crawled_at,
                sites.name AS site_name,
                sites.site_type,
                watch_targets.display_name AS target_name,
                watch_targets.style,
                post_marks.is_read,
                post_marks.useful,
                post_marks.refine,
                post_marks.noise,
                post_marks.note
            FROM posts
            JOIN sites ON sites.id = posts.site_id
            JOIN watch_targets ON watch_targets.id = posts.target_id
            JOIN post_marks ON post_marks.post_id = posts.id
            WHERE watch_targets.enabled = 1
              AND sites.enabled = 1
              AND post_marks.noise = 0
              AND post_marks.useful = 1
              AND substr(COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at), 1, 10) BETWEEN ? AND ?
            ORDER BY
              post_marks.useful DESC,
              COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at) DESC,
              posts.id DESC
            """,
            (start_date, end_date),
        ).fetchall()
    return [
        {
            "post_id": row["id"],
            "site": row["site_name"],
            "author": row["target_name"],
            "style": row["style"] or "未分类",
            "published_at": row["published_at"] or row["crawled_at"],
            "title": row["title"] or "",
            "content": row["content"] or "",
            "url": row["url"] or "",
            "marks": {
                "read": bool(row["is_read"]),
                "useful": bool(row["useful"]),
                "refine": bool(row["refine"]),
                "noise": bool(row["noise"]),
                "note": row["note"] or "",
            },
        }
        for row in rows
    ]


def write_outputs(records: list[dict], label: str, start_date: str, end_date: str) -> tuple[Path, Path]:
    out_dir = CLOUD_ROOT / "review_evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"marked_evidence_{label}.json"
    md_path = out_dir / f"marked_evidence_{label}.md"
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "range": {"start": start_date, "end": end_date, "label": label},
        "selection_rule": "人工标记证据池：只纳入有用，自动排除噪音；AI复盘阶段基于这些人工筛选内容再总结。",
        "records": records,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")

    lines = [
        f"# 人工标记复盘证据池 {start_date} 至 {end_date}",
        "",
        f"> 生成时间：{payload['generated_at']}；records: {len(records)}",
        "",
        "规则：只纳入 `有用`，排除 `噪音`。",
        "",
    ]
    for index, item in enumerate(records, 1):
        tags = []
        if item["marks"]["useful"]:
            tags.append("有用")
        lines.extend(
            [
                f"## {index}. {' / '.join(tags)} · {item['site']} / {item['author']} / {item['style']}",
                "",
                f"- 时间：{item['published_at']}",
                f"- 标题：{item['title'] or '(无标题)'}",
                f"- 链接：{item['url'] or '(无链接)'}",
                "",
                item["content"].strip(),
                "",
                "---",
                "",
            ]
        )
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="导出人工标记的复盘证据池。")
    parser.add_argument("--preset", default="recent3", choices=["today", "recent3", "weekend", "custom"])
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    args = parser.parse_args()

    start_date, end_date, label = date_window(args.preset, args.start, args.end)
    records = fetch_evidence(start_date, end_date)
    json_path, md_path = write_outputs(records, label, start_date, end_date)
    print(f"导出完成：{len(records)} 条")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
