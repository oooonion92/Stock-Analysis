from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from crawl_nga_author_replies import (
    PROFILE_DIR,
    enrich_records_with_detail_dates,
    extract_records,
    extract_html_records,
    find_browser,
    load_html_with_retry,
    nga_author_page_url,
    nga_search_url,
    now_iso,
    safe_json_loads,
)
from forum_db import connect, insert_posts, upsert_site, upsert_target


ROOT = Path(__file__).resolve().parents[3]
CLOUD_ROOT = Path(r"D:\OneDrive\Stock\Replies collect")
FALLBACK_OUTPUT_DIR = ROOT / "02_daily_replay" / "source_notes" / "crawled_forum_posts" / "nga_history"

AUTHOR_ID = "25859713"
AUTHOR_NAME = "ddddd519"


def output_root() -> Path:
    if CLOUD_ROOT.exists():
        return CLOUD_ROOT / "history_backfill"
    return FALLBACK_OUTPUT_DIR


def parse_post_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        try:
            return datetime.fromtimestamp(int(text)).astimezone().replace(tzinfo=None)
        except (OSError, ValueError):
            return None

    normalized = text.replace("T", " ")
    normalized = re.sub(r"\+\d{2}:\d{2}$", "", normalized).strip()
    match = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?", normalized)
    if not match:
        return None

    year, month, day, hour, minute, second = match.groups()
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
        )
    except ValueError:
        return None


def dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for record in records:
        key = str(record.get("id") or record.get("url") or record.get("content") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def load_json_records_with_retry(
    page_obj,
    page_num: int,
    retries: int,
    retry_delay: float,
) -> list[dict[str, Any]]:
    url = nga_search_url(AUTHOR_ID, page_num, output_json=True)
    json_retries = min(retries, 2)
    for attempt in range(1, json_retries + 2):
        response = page_obj.goto(url, wait_until="domcontentloaded")
        if response is None:
            print(f"[WARN] JSON page {page_num}: no response, retry {attempt}/{json_retries}")
            time.sleep(retry_delay)
            continue

        raw = response.body()
        preview = raw[:1200].decode("utf-8", errors="ignore")
        if "ERROR:2048" in preview or "2048" in preview and "busy" in preview.lower():
            if attempt <= json_retries:
                print(f"[WARN] JSON page {page_num}: server busy, retry {attempt}/{json_retries}")
                time.sleep(retry_delay)
                continue
            return []

        try:
            payload = safe_json_loads(raw)
            return extract_records(payload, AUTHOR_ID, AUTHOR_NAME, page_num)
        except Exception as exc:
            if attempt <= json_retries:
                print(f"[WARN] JSON page {page_num}: parse failed ({exc}), retry {attempt}/{json_retries}")
                time.sleep(retry_delay)
                continue
            print(f"[WARN] JSON page {page_num}: parse failed after retries: {exc}")
            return []

    return []


def merge_json_dates(html_records: list[dict[str, Any]], json_records: list[dict[str, Any]]) -> None:
    by_post_id: dict[str, str] = {}
    by_thread_post: dict[tuple[str, str], str] = {}
    for record in json_records:
        published_at = str(record.get("published_at") or "")
        post_id = str(record.get("post_id") or "")
        thread_id = str(record.get("thread_id") or "")
        if post_id and published_at:
            by_post_id[post_id] = published_at
        if thread_id and post_id and published_at:
            by_thread_post[(thread_id, post_id)] = published_at

    for record in html_records:
        post_id = str(record.get("post_id") or "")
        thread_id = str(record.get("thread_id") or "")
        published_at = by_thread_post.get((thread_id, post_id)) or by_post_id.get(post_id)
        if published_at:
            record["published_at"] = published_at
            record["date_source"] = "json_postdate"
        else:
            record["topic_published_at"] = record.get("published_at") or record.get("topic_published_at") or ""
            record["published_at"] = ""
            record["date_source"] = "unknown"


def render_markdown(records: list[dict[str, Any]], max_page_seen: int) -> str:
    lines = [
        f"# NGA history backfill: {AUTHOR_NAME}",
        "",
        f"- author_id: `{AUTHOR_ID}`",
        f"- source: https://bbs.nga.cn/thread.php?searchpost=1&authorid={AUTHOR_ID}",
        f"- pages_checked: {max_page_seen}",
        f"- records: {len(records)}",
        "- stop_rule: page count only",
        f"- generated_at: {now_iso()}",
        "",
    ]

    for index, record in enumerate(records, 1):
        title = str(record.get("title") or "(no title)").strip()
        published_at = str(record.get("published_at") or "").strip() or "unknown"
        url = str(record.get("url") or record.get("source_search_url") or "").strip()
        content = str(record.get("content") or "").strip()
        lines.extend(
            [
                f"## {index}. {published_at} - {title}",
                "",
                f"- url: {url}",
                f"- thread_id: `{record.get('thread_id') or ''}`",
                f"- post_id: `{record.get('post_id') or ''}`",
                "",
                content,
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def write_outputs(records: list[dict[str, Any]], max_page_seen: int, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"nga_{AUTHOR_NAME}_{AUTHOR_ID}_pages_1_{max_page_seen}.jsonl"
    md_path = out_dir / f"nga_{AUTHOR_NAME}_{AUTHOR_ID}_pages_1_{max_page_seen}.md"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    md_path.write_text(render_markdown(records, max_page_seen), encoding="utf-8-sig")
    return jsonl_path, md_path


def write_db(records: list[dict[str, Any]], pages_checked: int) -> int:
    with connect() as conn:
        upsert_site(
            conn,
            name="NGA",
            base_url="https://bbs.nga.cn",
            site_type="nga",
            login_required=True,
            enabled=True,
            notes="NGA author pages crawled with the shared browser profile.",
        )
        target_id = upsert_target(
            conn,
            site_name="NGA",
            display_name=AUTHOR_NAME,
            external_user_id=AUTHOR_ID,
            profile_url=f"https://bbs.nga.cn/thread.php?searchpost=1&authorid={AUTHOR_ID}",
            target_type="history",
            style="unknown",
            enabled=False,
            crawl_pages=pages_checked,
            notes=f"Historical backfill pages 1-{pages_checked}; disabled for daily one-click collection.",
        )
        site_id = int(conn.execute("SELECT id FROM sites WHERE name = ?", ("NGA",)).fetchone()["id"])
        return insert_posts(conn, site_id, target_id, records)


def crawl_history(
    max_pages: int,
    delay: float,
    retries: int,
    retry_delay: float,
    headless: bool,
    empty_page_stop: int,
    detail_dates: bool,
) -> tuple[list[dict[str, Any]], int]:
    if not PROFILE_DIR.exists():
        raise SystemExit("Browser profile is missing. Run login_site.py for NGA first.")

    executable_path = find_browser()
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    empty_pages = 0
    max_page_seen = 0

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=executable_path,
            headless=headless,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page_obj = context.pages[0] if context.pages else context.new_page()

        try:
            for page_num in range(1, max_pages + 1):
                max_page_seen = page_num
                url = nga_author_page_url(AUTHOR_ID, page_num)
                print(f"Page {page_num}: loading {url}")
                json_records = load_json_records_with_retry(
                    page_obj=page_obj,
                    page_num=page_num,
                    retries=retries,
                    retry_delay=retry_delay,
                )
                html = load_html_with_retry(
                    page_obj=page_obj,
                    url=url,
                    page_num=page_num,
                    retries=retries,
                    retry_delay=retry_delay,
                )
                if html is None:
                    empty_pages += 1
                    print(f"Page {page_num}: skipped after retry failures")
                    if empty_pages >= empty_page_stop:
                        print(f"Stop: {empty_pages} consecutive empty/failed pages")
                        break
                    continue

                records = extract_html_records(html, AUTHOR_ID, AUTHOR_NAME, page_num)
                records = dedupe_records(records)
                merge_json_dates(records, json_records)
                if not records:
                    empty_pages += 1
                    print(f"Page {page_num}: no records")
                    if empty_pages >= empty_page_stop:
                        print(f"Stop: {empty_pages} consecutive empty pages")
                        break
                    time.sleep(delay)
                    continue

                empty_pages = 0
                if detail_dates:
                    enrich_records_with_detail_dates(page_obj, records, retries=retries, retry_delay=retry_delay)

                page_dates = [parse_post_datetime(record.get("published_at")) for record in records]
                page_dates = [value for value in page_dates if value is not None]

                for record in records:
                    key = str(record.get("id") or record.get("url") or record.get("content") or "")
                    if key and key not in seen:
                        seen.add(key)
                        all_records.append(record)

                oldest = min(page_dates).strftime("%Y-%m-%d") if page_dates else "unknown"
                newest = max(page_dates).strftime("%Y-%m-%d") if page_dates else "unknown"
                print(f"Page {page_num}: found {len(records)}, saved {len(records)}, date range {oldest} to {newest}")

                time.sleep(delay)
        finally:
            context.close()

    return all_records, max_page_seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill NGA history for ddddd519 by page count.")
    parser.add_argument("--max-pages", type=int, default=170, help="Safety cap for author search pages.")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=20)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--empty-page-stop", type=int, default=3, help="Stop after this many consecutive empty/failed pages.")
    parser.add_argument("--output-dir", type=Path, default=output_root())
    parser.add_argument("--write-db", action="store_true", help="Also write records to local SQLite under a disabled history target.")
    parser.add_argument("--detail-dates", action="store_true", help="Open each post detail page to verify dates. Slower; normally JSON dates are enough.")
    parser.add_argument("--headed", action="store_true", help="Show browser window for login/debugging.")
    args = parser.parse_args()

    records, pages_checked = crawl_history(
        max_pages=args.max_pages,
        delay=args.delay,
        retries=args.retries,
        retry_delay=args.retry_delay,
        headless=not args.headed,
        empty_page_stop=args.empty_page_stop,
        detail_dates=args.detail_dates,
    )

    jsonl_path, md_path = write_outputs(records, pages_checked, args.output_dir)
    print(f"Done: {len(records)} records saved from {pages_checked} pages")
    print(f"JSONL: {jsonl_path}")
    print(f"Markdown: {md_path}")

    if args.write_db:
        inserted = write_db(records, pages_checked)
        print(f"SQLite: {inserted} new records inserted")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
