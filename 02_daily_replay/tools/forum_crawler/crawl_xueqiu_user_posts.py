from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from crawl_nga_author_replies import find_browser, strip_html
from playwright.sync_api import Response, sync_playwright


PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"
HOME_URL = "https://xueqiu.com/"
FEED_ALIASES = {"", "feed", "home", "following", "关注流", "雪球关注流"}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def normalize_user_url(user_id_or_url: str) -> str:
    value = (user_id_or_url or "").strip()
    if value.lower() in FEED_ALIASES:
        return HOME_URL
    if value.startswith("http"):
        return value
    return f"https://xueqiu.com/u/{value}"


def extract_user_id(value: str) -> str:
    value = (value or "").strip()
    if value.lower() in FEED_ALIASES:
        return "following"
    if value.isdigit():
        return value
    parsed = urlparse(value)
    match = re.search(r"/u/(\d+)", parsed.path)
    return match.group(1) if match else value.rstrip("/").split("/")[-1]


def clean_xueqiu_text(raw: str) -> str:
    soup = BeautifulSoup(raw or "", "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    return strip_html(soup.get_text("\n"))


def parse_time(value: Any) -> str:
    if isinstance(value, (int, float)):
        # Xueqiu normally uses milliseconds.
        if value > 10_000_000_000:
            value = int(value) / 1000
        return datetime.fromtimestamp(value).astimezone().isoformat(timespec="seconds")
    return str(value or "")


def status_url(item: dict[str, Any], user_id: str, status_id: str) -> str:
    target = item.get("target") or item.get("url") or ""
    if isinstance(target, str) and target.startswith("http"):
        return target
    if isinstance(target, str) and target.startswith("/"):
        return f"https://xueqiu.com{target}"
    item_user = item.get("user") or {}
    author_id = str(item_user.get("id") or user_id or "following")
    return f"https://xueqiu.com/{author_id}/{status_id}"


def normalize_status(item: dict[str, Any], user_id: str, author_name: str, source_url: str) -> dict[str, Any] | None:
    if "status" in item and isinstance(item["status"], dict):
        item = item["status"]
    status_id = str(item.get("id") or item.get("id_str") or item.get("status_id") or "")
    raw_text = item.get("text") or item.get("description") or item.get("content") or ""
    title = strip_html(item.get("title") or "")
    text = clean_xueqiu_text(raw_text)
    if not status_id or (not text and not title):
        return None

    user = item.get("user") or {}
    if user_id == "following" and not user:
        return None
    author = str(user.get("screen_name") or user.get("name") or author_name or "雪球关注流")
    author_id = str(user.get("id") or user_id or "following")
    return {
        "id": f"xueqiu:{status_id}",
        "site": "雪球",
        "author": author,
        "author_id": author_id,
        "thread_id": "",
        "post_id": f"{author_id}:{status_id}",
        "title": title,
        "content": text,
        "published_at": parse_time(item.get("created_at") or item.get("timeBefore") or item.get("createdAt")),
        "url": status_url(item, author_id, status_id),
        "source_search_url": source_url,
        "crawl_time": now_iso(),
        "raw": item,
    }


def walk_status_dicts(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            has_id = any(key in item for key in ("id", "id_str", "status_id"))
            has_text = any(key in item for key in ("text", "description", "content", "title"))
            if has_id and has_text:
                found.append(item)
            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return found


def extract_from_payload(payload: Any, user_id: str, author_name: str, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in walk_status_dicts(payload):
        record = normalize_status(item, user_id, author_name, source_url)
        if record:
            records.append(record)
    return records


def capture_json_response(response: Response, captured: list[Any]) -> None:
    url = response.url
    if "xueqiu.com" not in url:
        return
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type and not url.endswith(".json") and "/statuses/" not in url:
        return
    try:
        text = response.text()
        payload = json.loads(text)
    except Exception:
        return
    captured.append({"url": url, "payload": payload})


def dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        key = record.get("id") or record.get("url") or record.get("content")
        if not key or key in seen:
            continue
        seen.add(str(key))
        result.append(record)
    return result


def extract_feed_records(captured: list[Any], author_name: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for entry in captured:
        url = entry.get("url", "") if isinstance(entry, dict) else ""
        payload = entry.get("payload", entry) if isinstance(entry, dict) else entry
        if "home_timeline" not in url or "source=user" not in url:
            continue
        records.extend(extract_from_payload(payload, "following", author_name or "雪球关注流", HOME_URL))
    return dedupe(records)


def crawl_feed(
    author_name: str,
    pages: int,
    delay: float,
    headless: bool,
    exists_checker: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    captured: list[Any] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=find_browser(),
            headless=headless,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", lambda response: capture_json_response(response, captured))
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)

        for page_no in range(1, pages + 1):
            page_records = extract_feed_records(captured, author_name)
            unseen_records = [record for record in page_records if str(record.get("id") or record.get("url") or record.get("content")) not in seen]
            if unseen_records and exists_checker and all(exists_checker(record) for record in unseen_records):
                print(f"雪球关注流第 {page_no} 轮：{len(unseen_records)} 条候选发言均已存在，停止继续滚动")
                break
            for record in unseen_records:
                seen.add(str(record.get("id") or record.get("url") or record.get("content")))
                records.append(record)
            captured.clear()
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(delay * 1000))

        context.close()

    records = dedupe(records)
    print(f"雪球关注流：提取 {len(records)} 条候选发言")
    return records


def crawl_user_timeline(
    user_id_or_url: str,
    author_name: str,
    pages: int,
    delay: float,
    headless: bool,
    exists_checker: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    user_id = extract_user_id(user_id_or_url)
    user_url = normalize_user_url(user_id_or_url)
    captured: list[Any] = []

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=find_browser(),
            headless=headless,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.on("response", lambda response: capture_json_response(response, captured))
        page.goto(user_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        for page_no in range(1, pages + 1):
            captured.clear()
            for api_url in (
                f"https://xueqiu.com/statuses/user_timeline.json?user_id={user_id}&page={page_no}&count=20",
                f"https://xueqiu.com/v4/statuses/user_timeline.json?user_id={user_id}&page={page_no}&count=20",
            ):
                try:
                    page.goto(api_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(800)
                except Exception:
                    pass
            page_records: list[dict[str, Any]] = []
            for entry in captured:
                payload = entry.get("payload", entry) if isinstance(entry, dict) else entry
                page_records.extend(extract_from_payload(payload, user_id, author_name, user_url))
            page_records = dedupe(page_records)
            unseen_records = [record for record in page_records if str(record.get("id") or record.get("url") or record.get("content")) not in seen]
            if unseen_records and exists_checker and all(exists_checker(record) for record in unseen_records):
                print(f"雪球用户 {user_id} 第 {page_no} 页：{len(unseen_records)} 条候选发言均已存在，停止继续翻页")
                break
            for record in unseen_records:
                seen.add(str(record.get("id") or record.get("url") or record.get("content")))
                records.append(record)
            time.sleep(delay)
        context.close()

    print(f"雪球用户 {user_id}：提取 {len(dedupe(records))} 条候选发言")
    return dedupe(records)


def crawl(
    user_id_or_url: str,
    author_name: str,
    pages: int,
    delay: float,
    headless: bool,
    exists_checker: Callable[[dict[str, Any]], bool] | None = None,
) -> list[dict[str, Any]]:
    user_id = extract_user_id(user_id_or_url)
    if user_id.lower() in FEED_ALIASES or user_id == "following":
        return crawl_feed(author_name, pages, delay, headless, exists_checker=exists_checker)
    return crawl_user_timeline(user_id_or_url, author_name, pages, delay, headless, exists_checker=exists_checker)


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取雪球关注流或指定用户动态。")
    parser.add_argument("--user", default="following", help="雪球用户 ID / 主页 URL；默认 following 表示首页关注流。")
    parser.add_argument("--name", default="")
    parser.add_argument("--pages", type=int, default=1)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    records = crawl(args.user, args.name, args.pages, args.delay, headless=not args.headed)
    preview = [
        {
            "author": record["author"],
            "published_at": record["published_at"],
            "url": record["url"],
            "content": record["content"][:120],
        }
        for record in records[:5]
    ]
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    print(f"完成：{len(records)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
