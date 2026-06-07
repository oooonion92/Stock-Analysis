from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"
OUTPUT_DIR = ROOT / "02_daily_replay" / "source_notes" / "crawled_forum_posts" / "nga"
DEFAULT_AUTHOR_ID = "150058"
DEFAULT_AUTHOR_NAME = "-阿狼-"


def find_browser() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("未找到 Chrome/Edge，请先安装浏览器。")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def strip_html(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = re.sub(r"\[/?(?:quote|b|i|url|img|size|color)[^\]]*\]", "", text, flags=re.I)
    soup = BeautifulSoup(text, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    cleaned = soup.get_text("")
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"[ \t]*\n[ \t]*", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def decode_nga_bytes(value: str, prefer_gbk: bool = True) -> str:
    raw = value.encode("latin-1", errors="ignore")
    if not raw:
        return value

    encodings = ("gb18030", "gbk", "utf-8") if prefer_gbk else ("utf-8", "gb18030", "gbk")
    candidates: list[str] = []
    for encoding in encodings:
        try:
            candidates.append(raw.decode(encoding))
        except UnicodeDecodeError:
            continue

    if not candidates:
        return raw.decode("utf-8", errors="replace")

    def score(text: str) -> int:
        cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
        bad = text.count("\ufffd") * 20 + text.count("锟") * 10
        mojibake = sum(char in "ÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß" for char in text)
        return cjk * 3 - bad - mojibake

    return max(candidates, key=score)


def decode_nga_strings(value: Any, prefer_gbk: bool = True) -> Any:
    if isinstance(value, dict):
        return {
            decode_nga_bytes(key, prefer_gbk=False): decode_nga_strings(child, prefer_gbk=prefer_gbk)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [decode_nga_strings(child, prefer_gbk=prefer_gbk) for child in value]
    if isinstance(value, str):
        return decode_nga_bytes(value, prefer_gbk=prefer_gbk)
    return value


def safe_json_loads(raw: bytes | str) -> Any:
    if isinstance(raw, bytes):
        text = raw.decode("latin-1")
        payload = json.loads(text)
        return decode_nga_strings(payload, prefer_gbk=True)
    text = raw.strip()
    if text.startswith("window.__"):
        text = text[text.find("{") :]
    return json.loads(text)


def text_preview(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw[:1000].decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw[:1000].decode("utf-8", errors="replace")


def is_server_busy(raw: bytes) -> bool:
    preview = text_preview(raw)
    return "2048" in preview and "服务器忙" in preview


def is_login_required(raw: bytes) -> bool:
    preview = text_preview(raw)
    return "你必须登录" in preview or ("登录" in preview and "post" not in preview.lower())


def nga_search_url(author_id: str, page: int, output_json: bool = True) -> str:
    params = {
        "searchpost": "1",
        "authorid": author_id,
        "page": str(page),
    }
    if output_json:
        params["__output"] = "8"
    return "https://bbs.nga.cn/thread.php?" + urlencode(params)


def nga_author_page_url(author_id: str, page: int) -> str:
    params = {
        "searchpost": "1",
        "authorid": author_id,
        "page": str(page),
    }
    return "https://bbs.nga.cn/thread.php?" + urlencode(params)


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def post_url(item: dict[str, Any]) -> str:
    tid = item.get("tid") or item.get("thread_id") or item.get("t_id")
    pid = item.get("pid") or item.get("post_id")
    if tid and pid:
        return f"https://bbs.nga.cn/read.php?tid={tid}&pid={pid}"
    if tid:
        return f"https://bbs.nga.cn/read.php?tid={tid}"
    return ""


def read_post_url(tid: str, pid: str) -> str:
    return f"https://bbs.nga.cn/read.php?tid={tid}&pid={pid}"


def read_thread_page_url(tid: str, page: int | str) -> str:
    return f"https://bbs.nga.cn/read.php?tid={tid}&page={page}"


def normalize_candidate(item: dict[str, Any], author_id: str, author_name: str, page: int) -> dict[str, Any] | None:
    content = (
        item.get("content")
        or item.get("postcontent")
        or item.get("subject")
        or item.get("alterinfo")
        or ""
    )
    title = item.get("subject") or item.get("title") or item.get("thread_subject") or ""
    cleaned_content = strip_html(content)
    cleaned_title = strip_html(title)

    if not cleaned_content and not cleaned_title:
        return None

    item_author_id = str(item.get("authorid") or item.get("author_id") or item.get("uid") or author_id)
    item_author_name = strip_html(item.get("author") or item.get("username") or item.get("poster") or author_name)
    if item_author_id not in ("", author_id) and item_author_name not in ("", author_name):
        return None

    created = item.get("postdate") or item.get("timestamp") or item.get("time") or item.get("lastpost")
    if isinstance(created, (int, float)) or (isinstance(created, str) and created.isdigit()):
        created_at = datetime.fromtimestamp(int(created)).astimezone().isoformat(timespec="seconds")
    else:
        created_at = str(created or "")

    tid = str(item.get("tid") or item.get("thread_id") or item.get("t_id") or "")
    pid = str(item.get("pid") or item.get("post_id") or "")
    record_id = f"nga:{tid}:{pid}" if tid or pid else f"nga:{author_id}:page{page}:{hash(cleaned_content)}"

    return {
        "id": record_id,
        "site": "NGA",
        "author": item_author_name or author_name,
        "author_id": item_author_id or author_id,
        "page": page,
        "thread_id": tid,
        "post_id": pid,
        "title": cleaned_title,
        "content": cleaned_content,
        "published_at": created_at,
        "url": post_url(item),
        "source_search_url": nga_search_url(author_id, page, output_json=False),
        "crawl_time": now_iso(),
    }


def extract_records(payload: Any, author_id: str, author_name: str, page: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in iter_dicts(payload):
        if not any(key in item for key in ("content", "postcontent", "subject", "pid", "tid")):
            continue
        record = normalize_candidate(item, author_id, author_name, page)
        if not record:
            continue
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        records.append(record)
    return records


def extract_html_records(html: str, author_id: str, author_name: str, page: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for content_node in soup.select("span[id^='postcontent']"):
        match = re.match(r"postcontent(\d+)_(\d+)", content_node.get("id", ""))
        if not match:
            continue
        tid, pid = match.groups()

        container = content_node.find_parent("td", class_="c2")
        title = ""
        if container:
            title_node = container.select_one("a.topic")
            title = strip_html(title_node.get_text("\n") if title_node else "")

        row = content_node.find_parent("tr")
        author = author_name
        created_at = ""
        if row:
            author_node = row.select_one("a.author")
            if author_node:
                author = strip_html(author_node.get_text("\n")) or author_name
            date_node = row.select_one("span.postdate")
            timestamp = strip_html(date_node.get_text("\n") if date_node else "")
            if timestamp.isdigit():
                created_at = datetime.fromtimestamp(int(timestamp)).astimezone().isoformat(timespec="seconds")
            else:
                created_at = timestamp

        content = strip_html(content_node.decode_contents())
        record_id = f"nga:{tid}:{pid}"
        if record_id in seen:
            continue
        seen.add(record_id)
        records.append(
            {
                "id": record_id,
                "site": "NGA",
                "author": author,
                "author_id": author_id,
                "page": page,
                "thread_id": tid,
                "post_id": pid,
                "title": title,
                "content": content,
                "published_at": created_at,
                "topic_published_at": created_at,
                "url": read_post_url(tid, pid),
                "source_search_url": nga_author_page_url(author_id, page),
                "crawl_time": now_iso(),
            }
        )

    return records


def extract_detail_post_date(html: str, pid: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    anchor = soup.find(id=f"pid{pid}Anchor")
    row = anchor.find_parent("tr") if anchor else None
    if row is None:
        row = soup.find("tr", class_=re.compile(r"\bpostrow\b"))
    if row is None:
        return ""
    date_node = row.select_one("span[id^='postdate']")
    return strip_html(date_node.get_text("\n") if date_node else "")


def max_thread_page(html: str) -> int:
    soup = BeautifulSoup(html, "lxml")
    pages: list[int] = []
    for link in soup.select("a[href*='page=']"):
        href = link.get("href") or ""
        match = re.search(r"[?&]page=(\d+)", href)
        if match:
            pages.append(int(match.group(1)))
        text = strip_html(link.get_text(""))
        if text.isdigit():
            pages.append(int(text))
    return max(pages) if pages else 1


def extract_thread_author_records(
    html: str,
    tid: str,
    title: str,
    author_id: str,
    author_name: str,
    source_url: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    records: list[dict[str, Any]] = []
    for row in soup.select("tr.postrow"):
        uid_node = row.select_one('a[name="uid"]')
        uid = strip_html(uid_node.get_text("") if uid_node else "")
        author_node = row.select_one("a.userlink.author, a.author")
        author = strip_html(author_node.get_text("") if author_node else author_name)
        if uid != author_id and author_name not in author:
            continue

        pid_anchor = row.select_one("a[id^='pid'][id$='Anchor']")
        pid = ""
        if pid_anchor:
            pid = (pid_anchor.get("id") or "").replace("pid", "").replace("Anchor", "")
        if not pid:
            continue

        date_node = row.select_one("span[id^='postdate']")
        published_at = strip_html(date_node.get_text("\n") if date_node else "")
        content_node = row.select_one("span[id^='postcontent']")
        content = strip_html(content_node.decode_contents() if content_node else row.decode_contents())
        if not content:
            continue

        records.append(
            {
                "id": f"nga:{tid}:{pid}",
                "site": "NGA",
                "author": author or author_name,
                "author_id": author_id,
                "page": "",
                "thread_id": tid,
                "post_id": pid,
                "title": title,
                "content": content,
                "published_at": published_at,
                "url": read_post_url(tid, pid),
                "source_search_url": source_url,
                "crawl_time": now_iso(),
            }
        )
    return records


def scan_active_threads_for_author(
    page_obj: Page,
    seed_records: list[dict[str, Any]],
    author_id: str,
    author_name: str,
    retries: int,
    retry_delay: float,
    max_threads: int = 5,
    back_pages: int = 3,
) -> list[dict[str, Any]]:
    threads: dict[str, dict[str, Any]] = {}
    for record in seed_records:
        tid = str(record.get("thread_id") or "")
        if tid and tid not in threads:
            threads[tid] = record
        if len(threads) >= max_threads:
            break

    found: list[dict[str, Any]] = []
    for tid, seed in threads.items():
        first_html = load_html_with_retry(
            page_obj=page_obj,
            url=read_thread_page_url(tid, "e"),
            page_num=0,
            retries=retries,
            retry_delay=retry_delay,
        )
        if not first_html:
            continue
        last_page = max_thread_page(first_html)
        pages = list(range(last_page, max(0, last_page - back_pages), -1))
        for page_no in pages:
            if page_no == last_page:
                html = first_html
            else:
                html = load_html_with_retry(
                    page_obj=page_obj,
                    url=read_thread_page_url(tid, page_no),
                    page_num=page_no,
                    retries=retries,
                    retry_delay=retry_delay,
                )
            if not html:
                continue
            found.extend(
                extract_thread_author_records(
                    html=html,
                    tid=tid,
                    title=str(seed.get("title") or ""),
                    author_id=author_id,
                    author_name=author_name,
                    source_url=str(seed.get("source_search_url") or ""),
                )
            )
    return found


def enrich_records_with_detail_dates(
    page_obj: Page,
    records: list[dict[str, Any]],
    retries: int,
    retry_delay: float,
) -> None:
    for index, record in enumerate(records, 1):
        tid = str(record.get("thread_id") or "")
        pid = str(record.get("post_id") or "")
        if not tid or not pid:
            continue
        html = load_html_with_retry(
            page_obj=page_obj,
            url=read_post_url(tid, pid),
            page_num=index,
            retries=retries,
            retry_delay=retry_delay,
        )
        if not html:
            continue
        detail_date = extract_detail_post_date(html, pid)
        if detail_date:
            record["published_at"] = detail_date


def load_html_with_retry(
    page_obj: Page,
    url: str,
    page_num: int,
    retries: int,
    retry_delay: float,
) -> str | None:
    for attempt in range(1, retries + 2):
        response = page_obj.goto(url, wait_until="domcontentloaded")
        if response is None:
            print(f"[WARN] 第 {page_num} 页第 {attempt} 次无响应")
            time.sleep(retry_delay)
            continue

        raw = response.body()
        if is_server_busy(raw):
            if attempt <= retries:
                print(f"[WARN] 第 {page_num} 页服务器忙，{retry_delay:g} 秒后重试 {attempt}/{retries}")
                time.sleep(retry_delay)
                continue
            print(f"[WARN] 第 {page_num} 页多次服务器忙，跳过")
            return None

        body_text = ""
        try:
            body_text = page_obj.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = text_preview(raw)

        if "ERROR:2048" in body_text or "服务器忙,请稍后重试" in body_text:
            if attempt <= retries:
                print(f"[WARN] 第 {page_num} 页服务器忙，{retry_delay:g} 秒后重试 {attempt}/{retries}")
                time.sleep(retry_delay)
                continue
            print(f"[WARN] 第 {page_num} 页多次服务器忙，跳过")
            return None

        if is_login_required(raw) or "你必须登录" in body_text:
            raise SystemExit(f"第 {page_num} 页似乎未登录或被拦截，请重新运行 login_nga.py。")

        return page_obj.content()

    return None


def render_markdown(records: list[dict[str, Any]], author_name: str, author_id: str) -> str:
    lines = [
        f"# NGA 作者回帖抓取：{author_name}",
        "",
        f"- author_id: `{author_id}`",
        f"- records: {len(records)}",
        f"- generated_at: {now_iso()}",
        "",
    ]
    for index, record in enumerate(records, 1):
        lines.extend(
            [
                f"## {index}. {record.get('title') or '(无标题)'}",
                "",
                f"- 时间：{record.get('published_at') or '未知'}",
                f"- 链接：{record.get('url') or record.get('source_search_url')}",
                "",
                record.get("content", "").strip(),
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def crawl(
    author_id: str,
    author_name: str,
    pages: int,
    delay: float,
    retries: int,
    retry_delay: float,
    headless: bool,
) -> list[dict[str, Any]]:
    if not PROFILE_DIR.exists():
        raise SystemExit("还没有浏览器登录资料夹。请先运行 login_nga.py 并手动登录。")

    executable_path = find_browser()
    all_records: list[dict[str, Any]] = []
    seen: set[str] = set()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=executable_path,
            headless=headless,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page_obj = context.pages[0] if context.pages else context.new_page()

        for page_num in range(1, pages + 1):
            url = nga_author_page_url(author_id, page_num)
            html = load_html_with_retry(
                page_obj=page_obj,
                url=url,
                page_num=page_num,
                retries=retries,
                retry_delay=retry_delay,
            )
            if html is None:
                continue

            records = extract_html_records(html, author_id, author_name, page_num)
            enrich_records_with_detail_dates(page_obj, records, retries=retries, retry_delay=retry_delay)
            records.extend(
                scan_active_threads_for_author(
                    page_obj=page_obj,
                    seed_records=records,
                    author_id=author_id,
                    author_name=author_name,
                    retries=retries,
                    retry_delay=retry_delay,
                )
            )
            print(f"第 {page_num} 页：提取 {len(records)} 条候选发言")
            for record in records:
                if record["id"] in seen:
                    continue
                seen.add(record["id"])
                all_records.append(record)
            time.sleep(delay)

        context.close()

    return all_records


def main() -> int:
    parser = argparse.ArgumentParser(description="抓取 NGA 指定作者的回帖发言。")
    parser.add_argument("--author-id", default=DEFAULT_AUTHOR_ID)
    parser.add_argument("--author-name", default=DEFAULT_AUTHOR_NAME)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，便于排查登录状态。")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = crawl(
        author_id=args.author_id,
        author_name=args.author_name,
        pages=args.pages,
        delay=args.delay,
        retries=args.retries,
        retry_delay=args.retry_delay,
        headless=not args.headed,
    )

    jsonl_path = OUTPUT_DIR / f"author_{args.author_id}_replies.jsonl"
    md_path = OUTPUT_DIR / f"author_{args.author_id}_replies.md"

    with jsonl_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    md_path.write_text(render_markdown(records, args.author_name, args.author_id), encoding="utf-8-sig")

    print(f"完成：{len(records)} 条")
    print(f"JSONL: {jsonl_path}")
    print(f"Markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
