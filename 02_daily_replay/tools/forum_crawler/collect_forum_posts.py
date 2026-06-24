from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import stat
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from crawl_watchlist import crawl_target
from export_posts import OUTPUT_ROOT, export_all_posts
from forum_paths import CLOUD_REPORTS_ROOT, CLOUD_ROOT, CLOUD_WATCH_TARGETS
from forum_db import connect, list_enabled_targets
from import_watch_targets import import_csv


REPORT_DIR = CLOUD_REPORTS_ROOT

LEGACY_CLOUD_EXPORTS = (
    CLOUD_ROOT / "今日汇总.md",
    CLOUD_ROOT / "最近7天汇总.md",
    CLOUD_ROOT / "趋势高手汇总.md",
    CLOUD_ROOT / "短线高手汇总.md",
    CLOUD_ROOT / "_index.md",
    CLOUD_ROOT / "authors",
    CLOUD_ROOT / "raw_jsonl",
    CLOUD_ROOT / "reports",
)


def remove_readonly(func, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def cleanup_legacy_cloud_exports() -> tuple[int, list[str]]:
    removed = 0
    warnings: list[str] = []
    for path in LEGACY_CLOUD_EXPORTS:
        try:
            if path.is_dir():
                shutil.rmtree(path, onexc=remove_readonly)
                removed += 1
            elif path.exists():
                path.unlink()
                removed += 1
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
    return removed, warnings


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


def fetch_posts_for_summary(conn, days: int | None = None, style: str | None = None, limit: int | None = None) -> list:
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
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        filtered = []
        for row in rows:
            parsed = parse_post_time(row["published_at"] or row["crawled_at"])
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
        specs = [
            ("最近3天汇总.md", "最近3天高手发言汇总", 3, None, None),
        ]
        for filename, title, days, style, limit in specs:
            path = CLOUD_ROOT / filename
            rows = fetch_posts_for_summary(conn, days=days, style=style, limit=limit)
            path.write_text(render_summary(title, rows), encoding="utf-8-sig")
            paths.append(path)
    return paths


def write_reader_dashboard(days: int = 14, limit: int | None = None) -> Path:
    path = CLOUD_ROOT / "高手发言阅读看板.html"
    with connect() as conn:
        rows = fetch_posts_for_summary(conn, days=days, limit=limit)

    grouped: dict[str, dict[str, dict[str, list]]] = {}
    for row in rows:
        date = post_date(row)
        style = row["style"] or "未分类"
        source = f"{row['site_name']} / {row['author_name']}"
        grouped.setdefault(date, {}).setdefault(style, {}).setdefault(source, []).append(row)

    dates = sorted(grouped.keys(), key=date_sort_key, reverse=True)
    selected_date = dates[0] if dates else ""
    total_records = sum(len(grouped[date][style][source]) for date in grouped for style in grouped[date] for source in grouped[date][style])
    generated_at = datetime.now().isoformat(timespec="seconds")

    sections: list[str] = []
    for date in dates:
        sections.append(
            f'<section class="date-section" data-date="{html.escape(date)}" '
            f'{"hidden" if date != selected_date else ""}>'
        )
        sections.append(f'<div class="date-heading"><span>{html.escape(date)}</span><em>{sum(len(grouped[date][style][source]) for style in grouped[date] for source in grouped[date][style])} records</em></div>')
        for style in sorted(grouped[date]):
            sections.append(f'<h2 class="style-heading">{html.escape(style)}</h2>')
            for source in sorted(grouped[date][style]):
                anchor = html_id(date, style, source)
                records = grouped[date][style][source]
                sections.append(
                    f'<section class="author-section" id="{anchor}" data-date="{html.escape(date)}" '
                    f'data-style="{html.escape(style)}" data-source="{html.escape(source)}" data-count="{len(records)}">'
                )
                sections.append(f'<h3>{html.escape(source)} <span>{len(records)}</span></h3>')
                for index, row in enumerate(records, 1):
                    content = (row["content"] or "").strip()
                    if not content:
                        continue
                    title = clean_title(row["title"])
                    url = row["url"] or ""
                    sections.append('<article class="post">')
                    sections.append('<div class="post-meta">')
                    sections.append(f'<span>{html.escape(format_time(row["published_at"] or row["crawled_at"]))}</span>')
                    sections.append(f'<span>{html.escape(post_author_name(row))}</span>')
                    if title:
                        sections.append(f'<span>{html.escape(title)}</span>')
                    if url:
                        sections.append(f'<a href="{html.escape(url)}" target="_blank" rel="noopener">查看原帖</a>')
                    sections.append('</div>')
                    sections.append(f'<div class="content">{render_text_html(content)}</div>')
                    sections.append('</article>')
                sections.append('</section>')
        sections.append('</section>')

    text = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>高手发言阅读看板</title>
  <style>
    :root {{
      --bg: #f5f6f2;
      --panel: #ffffff;
      --ink: #20242a;
      --muted: #68707a;
      --line: #dfe3e6;
      --accent: #1f6feb;
      --accent-soft: #eaf2ff;
      --green: #2f7d57;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", Arial, sans-serif;
      line-height: 1.72;
    }}
    .sidebar {{
      position: fixed;
      inset: 0 auto 0 0;
      width: 340px;
      padding: 22px 18px;
      overflow-y: auto;
      background: #fbfcfa;
      border-right: 1px solid var(--line);
    }}
    .brand h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      line-height: 1.25;
    }}
    .brand p {{
      margin: 0 0 20px;
      color: var(--muted);
      font-size: 13px;
    }}
    .nav-title {{
      margin: 18px 0 10px;
      font-size: 13px;
      color: var(--muted);
      font-weight: 700;
      letter-spacing: 0;
    }}
    .author-nav {{
      display: grid;
      gap: 8px;
    }}
    .author-nav a {{
      display: block;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      color: var(--ink);
      text-decoration: none;
      font-size: 14px;
    }}
    .author-nav a:hover,
    .author-nav a.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
      color: #0b4fb3;
    }}
    .author-nav .style-label {{
      margin: 10px 0 2px;
      color: var(--green);
      font-size: 12px;
      font-weight: 800;
    }}
    .date-control {{
      margin-top: 22px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }}
    label {{
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    select {{
      width: 100%;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
      font-size: 15px;
    }}
    .meta {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 12px;
    }}
    main {{
      margin-left: 340px;
      padding: 30px 44px 80px;
    }}
    .reader {{
      width: min(1180px, 100%);
    }}
    .date-heading {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 18px;
      padding-bottom: 14px;
      border-bottom: 1px solid var(--line);
    }}
    .date-heading span {{
      font-size: 28px;
      font-weight: 800;
    }}
    .date-heading em {{
      color: var(--muted);
      font-style: normal;
    }}
    .style-heading {{
      margin: 28px 0 12px;
      font-size: 22px;
    }}
    .author-section {{
      scroll-margin-top: 18px;
      margin-bottom: 34px;
    }}
    .author-section h3 {{
      margin: 0 0 12px;
      font-size: 19px;
    }}
    .author-section h3 span {{
      margin-left: 6px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 500;
    }}
    .post {{
      margin: 0 0 16px;
      padding: 18px 20px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .post-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .post-meta a {{
      color: var(--accent);
      text-decoration: none;
    }}
    .preview {{
      margin: 12px 0 10px;
      color: #0f3d2c;
      font-weight: 700;
    }}
    .content {{
      white-space: normal;
      font-size: 16px;
    }}
    @media (max-width: 860px) {{
      .sidebar {{
        position: static;
        width: auto;
        max-height: none;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      main {{
        margin-left: 0;
        padding: 22px 16px 60px;
      }}
      .date-heading span {{
        font-size: 23px;
      }}
    }}
  </style>
</head>
<body>
  <aside class="sidebar">
    <div class="brand">
      <h1>高手发言阅读看板</h1>
      <p>{html.escape(generated_at)} ｜ 最新日期 {html.escape(selected_date or "无")} ｜ {total_records} records</p>
    </div>
    <div class="nav-title">作者导航</div>
    <nav id="authorNav" class="author-nav"></nav>
    <div class="date-control">
      <label for="dateSelect">日期选择</label>
      <select id="dateSelect" data-latest-date="{html.escape(selected_date)}"></select>
    </div>
    <div class="meta">点击作者名后，右侧阅读区会跳到对应位置。</div>
  </aside>
  <main>
    <div class="reader">
      {''.join(sections)}
    </div>
  </main>
  <script>
    const dateSelect = document.getElementById('dateSelect');
    const authorNav = document.getElementById('authorNav');

    function dateRank(date) {{
      const time = Date.parse(`${{date}}T00:00:00`);
      return Number.isNaN(time) ? -1 : time;
    }}

    function availableDates() {{
      const dates = Array.from(document.querySelectorAll('.date-section'))
        .map(section => section.dataset.date)
        .filter(Boolean);
      return Array.from(new Set(dates)).sort((a, b) => dateRank(b) - dateRank(a) || b.localeCompare(a));
    }}

    function rebuildDateSelect() {{
      const dates = availableDates();
      dateSelect.innerHTML = '';
      dates.forEach(date => {{
        const option = document.createElement('option');
        option.value = date;
        option.textContent = date;
        dateSelect.appendChild(option);
      }});
      const latest = dates[0] || '';
      dateSelect.dataset.latestDate = latest;
      return latest;
    }}

    function showDate(date) {{
      document.querySelectorAll('.date-section').forEach(section => {{
        section.hidden = section.dataset.date !== date;
      }});
      renderAuthorNav(date);
      dateSelect.value = date;
      const activeSection = document.querySelector(`.date-section[data-date="${{CSS.escape(date)}}"]`);
      if (activeSection) window.scrollTo({{ top: activeSection.offsetTop - 16, behavior: 'smooth' }});
    }}

    function renderAuthorNav(date) {{
      authorNav.innerHTML = '';
      const sections = Array.from(document.querySelectorAll(`.author-section[data-date="${{CSS.escape(date)}}"]`));
      let lastStyle = '';
      sections.forEach(section => {{
        if (section.dataset.style !== lastStyle) {{
          const label = document.createElement('div');
          label.className = 'style-label';
          label.textContent = section.dataset.style;
          authorNav.appendChild(label);
          lastStyle = section.dataset.style;
        }}
        const link = document.createElement('a');
        link.href = `#${{section.id}}`;
        link.textContent = `${{section.dataset.source}} (${{section.dataset.count}})`;
        link.addEventListener('click', () => {{
          authorNav.querySelectorAll('a').forEach(item => item.classList.remove('active'));
          link.classList.add('active');
        }});
        authorNav.appendChild(link);
      }});
    }}

    dateSelect.addEventListener('change', event => showDate(event.target.value));
    const latestDate = rebuildDateSelect();
    if (latestDate) {{
      showDate(latestDate);
    }}
  </script>
</body>
</html>
"""
    path.write_text(text, encoding="utf-8-sig")
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
    parser.add_argument("--export-format", default="both", choices=["md", "jsonl", "both"])
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

    removed_legacy, cleanup_warnings = cleanup_legacy_cloud_exports()
    summary_paths = write_summary_files()
    dashboard_path = write_reader_dashboard()

    print(f"收集完成：{len(summary)} 个目标")
    if removed_legacy:
        print(f"已清理旧导出：{removed_legacy} 项")
    for warning in cleanup_warnings:
        print(f"[WARN] 旧导出暂未清理：{warning}")
    print(f"三日滚动汇总：{summary_paths[0]}")
    print(f"阅读看板：{dashboard_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
