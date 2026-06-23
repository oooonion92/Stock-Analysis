from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from crawl_watchlist import crawl_target
from export_posts import OUTPUT_ROOT, export_all_posts
from forum_paths import CLOUD_REPORTS_ROOT, CLOUD_ROOT, CLOUD_WATCH_TARGETS
from forum_db import connect, list_enabled_targets
from import_watch_targets import import_csv

TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from render_expert_reader_board import parse_markdown, render_html


REPORT_DIR = CLOUD_REPORTS_ROOT


def clean_title(value: str | None) -> str:
    title = (value or "").strip()
    if not title or title in {"(无标题)", "无标题"}:
        return ""
    return title


def format_time(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return "未知时间"
    return value.replace("T", " ").replace("+08:00", "")


def first_non_empty_line(value: str, max_chars: int = 90) -> str:
    for line in (value or "").splitlines():
        cleaned = line.strip()
        if (
            not cleaned
            or cleaned.startswith("Reply to ")
            or cleaned in {"回复", "//"}
            or cleaned.startswith("@")
        ):
            continue
        if len(cleaned) > max_chars:
            return cleaned[:max_chars].rstrip() + "..."
        return cleaned
    return ""


def post_author_name(row) -> str:
    fallback = row["author_name"] or ""
    if row["site_name"] != "雪球":
        return fallback
    try:
        raw = json.loads(row["raw_json"] or "{}")
    except json.JSONDecodeError:
        return fallback
    return str(raw.get("author") or fallback)


def metadata_line(row) -> str:
    parts = [
        format_time(row["published_at"] or row["crawled_at"]),
        row["site_name"],
        post_author_name(row),
    ]
    title = clean_title(row["title"])
    if title:
        parts.append(title)
    if row["url"]:
        parts.append(f"[查看原帖]({row['url']})")
    return " ｜ ".join(parts)


def post_date(row) -> str:
    parsed = parse_post_time(row["published_at"] or row["crawled_at"])
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    value = str(row["published_at"] or row["crawled_at"] or "")
    return value[:10] if len(value) >= 10 else "未知日期"


def date_sort_key(value: str) -> tuple[int, datetime]:
    try:
        return (1, datetime.strptime(value, "%Y-%m-%d"))
    except ValueError:
        return (0, datetime.min)


def author_anchor(style_index: int, source_index: int) -> str:
    return f"author-{style_index}-{source_index}"


def html_id(*parts: object) -> str:
    raw = "-".join(str(part) for part in parts)
    return "".join(ch if ch.isalnum() else "-" for ch in raw).strip("-").lower()


def render_text_html(value: str) -> str:
    return html.escape(value or "").replace("\n", "<br>")


def should_show_preview(content: str, preview: str) -> bool:
    if not preview:
        return False
    return not (content or "").lstrip().startswith(preview)


def write_report(summary: list[dict], exported_paths: list[Path]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"collect_report_{stamp}.md"
    lines = [
        "# 高手发言收集报告",
        "",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 抓取结果",
        "",
        "| 站点 | 高手 | 分类 | 页数 | 找到 | 新增 | 状态 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in summary:
        lines.append(
            f"| {item['site']} | {item['name']} | {item['style']} | {item['pages']} | "
            f"{item['found']} | {item['new']} | {item['status']} |"
        )
    lines.extend(["", "## 导出文件", ""])
    for exported_path in exported_paths:
        lines.append(f"- `{exported_path}`")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return path


def write_export_index(exported_paths: list[Path]) -> Path:
    index_path = CLOUD_ROOT / "_index.md"
    grouped: dict[str, list[Path]] = {}
    for path in exported_paths:
        if path.suffix.lower() != ".md":
            continue
        try:
            style = path.relative_to(OUTPUT_ROOT).parts[1]
        except Exception:
            style = "未分类"
        grouped.setdefault(style, []).append(path)

    lines = [
        "# 高手发言导出索引",
        "",
        f"- 更新时间：{datetime.now().isoformat(timespec='seconds')}",
        "- [高手发言阅读看板](高手发言阅读看板.html)",
        "",
    ]
    for style in sorted(grouped):
        lines.extend([f"## {style}", ""])
        for path in sorted(grouped[style], key=lambda item: item.name):
            try:
                link = path.relative_to(CLOUD_ROOT).as_posix()
            except ValueError:
                link = path.as_posix()
            lines.append(f"- [{path.stem}]({link})")
        lines.append("")

    index_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return index_path


def parse_post_time(value: str) -> datetime | None:
    value = value or ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def fetch_posts_for_summary(
    conn,
    days: int | None = None,
    style: str | None = None,
    limit: int | None = None,
    target_date: str | None = None,
) -> list:
    rows = list(
        conn.execute(
            """
            SELECT
                posts.*,
                sites.name AS site_name,
                sites.site_type,
                watch_targets.display_name AS author_name,
                watch_targets.external_user_id,
                watch_targets.style
            FROM posts
            JOIN sites ON sites.id = posts.site_id
            JOIN watch_targets ON watch_targets.id = posts.target_id
            WHERE watch_targets.enabled = 1
            ORDER BY COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at) DESC, posts.id DESC
            """
        )
    )
    if style:
        rows = [row for row in rows if row["style"] == style]
    if target_date is not None:
        rows = [row for row in rows if post_date(row) == target_date]
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        filtered = []
        for row in rows:
            parsed = parse_post_time(row["published_at"])
            if parsed and parsed >= cutoff:
                filtered.append(row)
        rows = filtered
    if limit:
        rows = rows[:limit]
    return rows


def render_summary(title: str, rows) -> str:
    grouped: dict[str, dict[str, list]] = {}
    for row in rows:
        style = row["style"] or "未分类"
        source = f"{row['site_name']} / {row['author_name']}"
        grouped.setdefault(style, {}).setdefault(source, []).append(row)

    lines = [
        f"# {title}",
        "",
        f"> 更新时间：{datetime.now().isoformat(timespec='seconds')} ｜ records: {len(rows)}",
        "",
    ]
    if grouped:
        lines.extend(["## 作者导航", ""])
        for style_index, style in enumerate(sorted(grouped), 1):
            links = []
            for source_index, source in enumerate(sorted(grouped[style]), 1):
                count = len(grouped[style][source])
                links.append(f"[{source} ({count})](#{author_anchor(style_index, source_index)})")
            lines.extend([f"**{style}**", "", " · ".join(links), ""])

    index = 1
    for style_index, style in enumerate(sorted(grouped), 1):
        lines.extend([f"## {style}", ""])
        for source_index, source in enumerate(sorted(grouped[style]), 1):
            lines.extend([f'<a id="{author_anchor(style_index, source_index)}"></a>', ""])
            lines.extend([f"### {source}", ""])
            for row in grouped[style][source]:
                content = (row["content"] or "").strip()
                if not content:
                    continue
                preview = first_non_empty_line(content)
                lines.extend(
                    [
                        f"#### {index}. {format_time(row['published_at'] or row['crawled_at'])}",
                        "",
                        f"> {metadata_line(row)}",
                    ]
                )
                if should_show_preview(content, preview):
                    lines.extend(["", f"**速览：** {preview}"])
                lines.extend(
                    [
                        "",
                        content,
                        "",
                        "---",
                        "",
                    ]
                )
                index += 1
    return "\n".join(lines).strip() + "\n"


def write_summary_files() -> list[Path]:
    CLOUD_ROOT.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with connect() as conn:
        today = datetime.now().strftime("%Y-%m-%d")
        specs = [
            ("今日汇总.md", "今日高手发言汇总", 1, None, 200),
            ("最近7天汇总.md", "最近7天高手发言汇总", 7, None, 500),
            ("趋势高手汇总.md", "趋势高手发言汇总", 14, "趋势", 500),
            ("短线高手汇总.md", "短线高手发言汇总", 14, "短线", 500),
        ]
        specs[0] = (specs[0][0], specs[0][1], None, specs[0][3], None, today)
        specs[1] = (*specs[1], None)
        specs[2] = (*specs[2], None)
        specs[3] = (*specs[3], None)
        for filename, title, days, style, limit, target_date in specs:
            path = CLOUD_ROOT / filename
            rows = fetch_posts_for_summary(conn, days=days, style=style, limit=limit, target_date=target_date)
            path.write_text(render_summary(title, rows), encoding="utf-8-sig")
            paths.append(path)
    return paths


def write_reader_dashboard(days: int = 14, limit: int | None = None) -> Path:
    path = CLOUD_ROOT / "高手发言阅读看板.html"
    summary_path = CLOUD_ROOT / "今日汇总.md"
    if not summary_path.exists():
        raise FileNotFoundError(f"未找到汇总文件：{summary_path}")
    board = parse_markdown(summary_path.read_text(encoding="utf-8-sig"))
    path.write_text(render_html(board), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="一键收集跟踪库中的高手发言，并导出可读文件。")
    parser.add_argument("--site", help="只收集指定网站，例如 NGA。")
    parser.add_argument("--style", choices=["短线", "趋势", "混合", "未知"], help="只收集指定分类。")
    parser.add_argument("--pages", type=int, help="覆盖数据库中的抓取页数。")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--retries", type=int, default=10)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，便于排查登录状态。")
    parser.add_argument("--limit", type=int, help="导出每个高手最近 N 条；不填则导出全部。")
    parser.add_argument("--export-format", default="jsonl", choices=["md", "jsonl", "both"])
    parser.add_argument("--skip-crawl", action="store_true", help="只从数据库导出，不访问网站。")
    parser.add_argument("--skip-watchlist-import", action="store_true", help="不从云端 watch_targets.csv 同步跟踪清单。")
    args = parser.parse_args()

    if not args.skip_watchlist_import and CLOUD_WATCH_TARGETS.exists():
        print(f"同步云端跟踪清单：{CLOUD_WATCH_TARGETS}")
        import_csv(CLOUD_WATCH_TARGETS)

    crawl_args = SimpleNamespace(
        pages=args.pages,
        delay=args.delay,
        retries=args.retries,
        retry_delay=args.retry_delay,
        headed=args.headed,
    )
    summary: list[dict] = []

    with connect() as conn:
        targets = list_enabled_targets(conn)
        if args.site:
            targets = [target for target in targets if target["site_name"] == args.site]
        if args.style:
            targets = [target for target in targets if target["style"] == args.style]

        if not targets:
            print("没有找到符合条件的启用目标。")
            return 0

        if args.skip_crawl:
            for target in targets:
                pages = args.pages if args.pages is not None else int(target["crawl_pages"])
                summary.append(
                    {
                        "site": target["site_name"],
                        "name": target["display_name"],
                        "style": target["style"],
                        "pages": pages,
                        "found": 0,
                        "new": 0,
                        "status": "skipped",
                    }
                )
        else:
            for target in targets:
                pages = args.pages if args.pages is not None else int(target["crawl_pages"])
                print(f"开始收集：{target['site_name']} / {target['display_name']} / {target['style']}")
                try:
                    found, new = crawl_target(conn, target, crawl_args)
                    status = "success"
                except Exception as exc:
                    found, new = 0, 0
                    status = f"failed: {exc}"
                    print(f"[WARN] {target['display_name']} 收集失败：{exc}")
                summary.append(
                    {
                        "site": target["site_name"],
                        "name": target["display_name"],
                        "style": target["style"],
                        "pages": pages,
                        "found": found,
                        "new": new,
                        "status": status,
                    }
                )

    formats = ["md", "jsonl"] if args.export_format == "both" else [args.export_format]
    exported_paths = export_all_posts(
        output_root=OUTPUT_ROOT,
        site_name=args.site,
        formats=formats,
        limit=args.limit,
    )
    report_path = write_report(summary, exported_paths)
    index_path = write_export_index(exported_paths)
    summary_paths = write_summary_files()
    dashboard_path = write_reader_dashboard()

    print(f"收集完成：{len(summary)} 个目标")
    print(f"导出文件：{len(exported_paths)} 个")
    print(f"汇总文件：{len(summary_paths)} 个")
    print(f"阅读看板：{dashboard_path}")
    print(f"报告：{report_path}")
    print(f"索引：{index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
