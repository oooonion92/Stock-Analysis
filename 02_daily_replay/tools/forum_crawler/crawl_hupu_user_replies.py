from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawl_nga_author_replies import find_browser, strip_html
from playwright.sync_api import sync_playwright


PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_profile_url(user_id_or_url: str) -> str:
    value = user_id_or_url.strip()
    if value.startswith("http"):
        return value
    return f"https://my.hupu.com/{value}?tabKey=2"


def extract_user_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        return value
    parsed = urlparse(value)
    match = re.search(r"/(\d+)", parsed.path)
    return match.group(1) if match else value.rstrip("/").split("/")[-1]


def clean_text(value: str) -> str:
    return strip_html((value or "").replace("\xa0", " ")).strip()


def extract_author_name(soup: BeautifulSoup, fallback: str) -> str:
    admin = soup.select_one("#bbs-admin-personal-center-container")
    if admin and admin.get("data-admininfo"):
        try:
            payload = json.loads(admin["data-admininfo"].replace("&quot;", '"'))
            if payload.get("postUserName"):
                return str(payload["postUserName"])
        except Exception:
            pass
    return fallback


def item_hash(user_id: str, published_at: str, content: str) -> str:
    value = f"{user_id}\n{published_at}\n{content}".encode("utf-8", errors="ignore")
    return hashlib.sha1(value).hexdigest()[:16]


def parse_items(html: str, profile_url: str, user_id: str, author_name: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    author = extract_author_name(soup, author_name)
    records: list[dict[str, Any]] = []

    for item in soup.select(".list-item"):
        reply_node = item.select_one(".list-item-reply")
        if reply_node is None:
            continue
        content = clean_text(reply_node.get_text("\n"))
        if not content:
            continue

        quote_node = item.select_one(".hasImgContent")
        quote = clean_text(quote_node.get_text("\n")) if quote_node else ""
        title_node = item.select_one(".shoImgWarp a")
        title = clean_text(title_node.get_text(" ")) if title_node else ""
        topic_node = item.select_one(".hasTopicName")
        topic = clean_text(topic_node.get_text(" ")) if topic_node else ""
        block_text = clean_text(item.get_text("\n"))
        match = re.search(r"发布于\s*([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", block_text)
        published_at = match.group(1) if match else ""
        post_id = item_hash(user_id, published_at, content)

        full_content = content
        if quote:
            full_content = f"{content}\n\n引用：{quote}"
        if topic:
            full_content = f"{full_content}\n\n来自：{topic}"

        records.append(
            {
                "id": f"hupu:{user_id}:{post_id}",
                "site": "虎扑",
                "author": author,
                "author_id": user_id,
                "thread_id": title,
                "post_id": f"{user_id}:{post_id}",
                "title": title or "虎扑回帖",
                "content": full_content,
                "published_at": published_at,
                "url": f"{profile_url}#reply-{post_id}",
                "source_search_url": profile_url,
                "crawl_time": now_iso(),
                "raw": {
                    "content": content,
                    "quote": quote,
                    "thread_title": title,
                    "topic": topic,
                    "block_text": block_text,
                },
            }
        )

    return records


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = record["post_id"]
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def crawl(
    user_id_or_url: str,
    author_name: str,
    pages: int,
    delay: float,
    headless: bool,
    exists_checker: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    user_id = extract_user_id(user_id_or_url)
    profile_url = normalize_profile_url(user_id_or_url)
    records: list[dict[str, Any]] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=find_browser(),
            headless=headless,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        seen: set[str] = set()
        for page_no in range(1, max(1, pages) + 1):
            page_records = dedupe(parse_items(page.content(), profile_url, user_id, author_name))
            unseen_records = [record for record in page_records if record["post_id"] not in seen]
            if unseen_records and exists_checker and all(exists_checker(record) for record in unseen_records):
                print(f"虎扑用户 {user_id} 第 {page_no} 轮：{len(unseen_records)} 条候选回帖均已存在，停止继续滚动")
                break
            for record in unseen_records:
                seen.add(record["post_id"])
                records.append(record)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(delay * 1000))
            time.sleep(delay)
        context.close()

    records = dedupe(records)
    print(f"虎扑用户 {user_id}：提取 {len(records)} 条候选回帖")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取虎扑个人中心回帖。")
    parser.add_argument("--user", required=True, help="虎扑用户 ID 或个人页 URL。")
    parser.add_argument("--name", default="")
    parser.add_argument("--pages", type=int, default=2, help="滚动加载次数。")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    records = crawl(args.user, args.name, args.pages, args.delay, headless=not args.headed)
    preview = [
        {
            "author": record["author"],
            "published_at": record["published_at"],
            "title": record["title"],
            "content": record["content"][:160],
        }
        for record in records[:5]
    ]
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print(f"完成：{len(records)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
