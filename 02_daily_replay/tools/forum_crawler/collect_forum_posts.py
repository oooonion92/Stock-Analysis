from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from crawl_watchlist import crawl_target
from export_posts import OUTPUT_ROOT, export_all_posts
from forum_db import ROOT, connect, list_enabled_targets


REPORT_DIR = ROOT / "02_daily_replay" / "source_notes" / "crawled_forum_posts" / "_reports"


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
    index_path = OUTPUT_ROOT / "_index.md"
    grouped: dict[str, list[Path]] = {}
    for path in exported_paths:
        try:
            style = path.relative_to(OUTPUT_ROOT).parts[1]
        except Exception:
            style = "未分类"
        grouped.setdefault(style, []).append(path)

    lines = [
        "# 高手发言导出索引",
        "",
        f"- 更新时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    for style in sorted(grouped):
        lines.extend([f"## {style}", ""])
        for path in sorted(grouped[style], key=lambda item: item.name):
            lines.append(f"- [{path.stem}]({path.as_posix()})")
        lines.append("")

    index_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8-sig")
    return index_path


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
    args = parser.parse_args()

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

    print(f"收集完成：{len(summary)} 个目标")
    print(f"导出文件：{len(exported_paths)} 个")
    print(f"报告：{report_path}")
    print(f"索引：{index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
