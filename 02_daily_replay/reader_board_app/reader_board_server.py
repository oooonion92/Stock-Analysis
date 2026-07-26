from __future__ import annotations

import argparse
import json
import re
import sqlite3
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


APP_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = APP_ROOT / "data" / "forum_watchlist.sqlite"
HOST = "127.0.0.1"
PORT = 8769
def parse_time(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", value)
    if match:
        month, day, hour, minute = map(int, match.groups())
        return datetime(date.today().year, month, day, hour, minute)
    return None


def parse_post_time(
    published_at: str | None,
    crawled_at: str | None,
    allow_crawled_fallback: bool = False,
) -> datetime | None:
    published = (published_at or "").strip()
    crawled = parse_time(crawled_at)
    if published and crawled and published == (crawled_at or "").strip():
        return crawled if allow_crawled_fallback else None
    parsed = parse_time(published)
    if parsed:
        return parsed

    base = crawled or datetime.now()
    match = re.fullmatch(r"(今天|昨天|前天)\s+(\d{1,2}):(\d{2})", published)
    if match:
        day_text, hour, minute = match.groups()
        offset = {"今天": 0, "昨天": 1, "前天": 2}[day_text]
        target_day = base.date() - timedelta(days=offset)
        return datetime.combine(target_day, datetime.min.time()).replace(hour=int(hour), minute=int(minute))

    match = re.fullmatch(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})", published)
    if match:
        month, day, hour, minute = map(int, match.groups())
        return datetime(base.year, month, day, hour, minute)

    return crawled if allow_crawled_fallback else None


def post_day(published_at: str | None, crawled_at: str | None) -> str:
    parsed = parse_post_time(published_at, crawled_at)
    return parsed.date().isoformat() if parsed else ""


def post_time_label(published_at: str | None, crawled_at: str | None) -> str:
    parsed = parse_post_time(published_at, crawled_at)
    if not parsed and crawled_at:
        crawled = parse_time(crawled_at)
        if crawled:
            return "抓取 " + crawled.strftime("%Y-%m-%d %H:%M")
    if not parsed:
        return str(published_at or crawled_at or "")
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
        return parsed.date().isoformat()
    return parsed.strftime("%Y-%m-%d %H:%M")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.create_function("post_day", 2, post_day)
    init_marks_db(conn)
    return conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def latest_post_date(conn: sqlite3.Connection) -> date:
    latest = conn.execute(
        "SELECT MAX(post_day(published_at, crawled_at)) AS latest FROM posts"
    ).fetchone()["latest"]
    if latest:
        return date.fromisoformat(str(latest))
    return date.today()


def latest_crawl_date(conn: sqlite3.Connection) -> date:
    latest = conn.execute(
        "SELECT MAX(substr(crawled_at, 1, 10)) AS latest FROM posts"
    ).fetchone()["latest"]
    if latest:
        return date.fromisoformat(str(latest))
    return date.today()


def min_post_date(conn: sqlite3.Connection) -> str:
    earliest = conn.execute(
        "SELECT MIN(post_day(published_at, crawled_at)) AS earliest FROM posts"
    ).fetchone()["earliest"]
    return str(earliest or "")


def resolve_date_range(
    conn: sqlite3.Connection,
    preset: str,
    start: str = "",
    end: str = "",
) -> tuple[str, str, str]:
    latest = latest_post_date(conn)
    if preset == "today":
        begin = finish = date.today()
        label = "今天"
    elif preset == "recent7":
        begin = latest - timedelta(days=6)
        finish = latest
        label = "最近7天"
    elif preset == "weekend":
        finish = latest
        begin = latest - timedelta(days=2)
        label = "最近3天"
    elif preset == "all":
        begin = min_post_date(conn) or latest.isoformat()
        finish = latest.isoformat()
        label = "全部日期"
        return begin, finish, label
    elif preset == "custom" and start and end:
        return start, end, f"{start} 至 {end}"
    else:
        begin = latest - timedelta(days=2)
        finish = latest
        label = "最近3天"
    return begin.isoformat(), finish.isoformat(), label


def init_marks_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS post_marks (
            post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
            is_read INTEGER NOT NULL DEFAULT 0,
            useful INTEGER NOT NULL DEFAULT 0,
            refine INTEGER NOT NULL DEFAULT 0,
            noise INTEGER NOT NULL DEFAULT 0,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_marks_useful ON post_marks(useful)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_marks_noise ON post_marks(noise)")
    conn.commit()


def mark_from_row(row: sqlite3.Row | None) -> dict:
    if row is None:
        return {"read": False, "useful": False, "refine": False, "noise": False, "note": ""}
    return {
        "read": bool(row["is_read"]),
        "useful": bool(row["useful"]),
        "refine": bool(row["refine"]),
        "noise": bool(row["noise"]),
        "note": row["note"] or "",
    }


def get_mark_map(conn: sqlite3.Connection, post_ids: list[int]) -> dict[int, dict]:
    if not post_ids:
        return {}
    placeholders = ",".join("?" for _ in post_ids)
    rows = conn.execute(
        f"SELECT * FROM post_marks WHERE post_id IN ({placeholders})",
        post_ids,
    ).fetchall()
    return {int(row["post_id"]): mark_from_row(row) for row in rows}


def marked_post_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM post_marks
            WHERE is_read = 1 OR useful = 1 OR refine = 1 OR noise = 1 OR note <> ''
            """
        ).fetchone()["count"]
    )


def set_post_mark(post_id: int, key: str, value: bool) -> dict:
    columns = {
        "read": "is_read",
        "useful": "useful",
        "noise": "noise",
    }
    if key not in columns:
        raise ValueError(f"Unsupported mark: {key}")
    stamp = now_iso()
    with connect() as conn:
        existing = conn.execute("SELECT * FROM post_marks WHERE post_id = ?", (post_id,)).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO post_marks(post_id, created_at, updated_at)
                VALUES(?, ?, ?)
                """,
                (post_id, stamp, stamp),
            )
        conn.execute(
            f"UPDATE post_marks SET {columns[key]} = ?, updated_at = ? WHERE post_id = ?",
            (int(value), stamp, post_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM post_marks WHERE post_id = ?", (post_id,)).fetchone()
        return mark_from_row(row)


def row_author(row: sqlite3.Row) -> str:
    if row["site_type"] != "xueqiu":
        return row["target_name"] or ""
    try:
        raw = json.loads(row["raw_json"] or "{}")
    except json.JSONDecodeError:
        return row["target_name"] or ""
    return str(raw.get("author") or row["target_name"] or "")


def reply_chain_from_raw(raw_json: str | None) -> list[dict[str, str]]:
    """Return only well-formed quoted context; the post body stays separate."""
    try:
        payload = json.loads(raw_json or "{}")
    except json.JSONDecodeError:
        return []
    chain = payload.get("replyChain")
    if not isinstance(chain, list):
        return []

    result: list[dict[str, str]] = []
    for item in chain:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or "").strip()
        if not body:
            continue
        result.append(
            {
                "author": str(item.get("author") or "").strip(),
                "time": str(item.get("time") or "").strip(),
                "body": body,
            }
        )
    return result


def post_date(row: sqlite3.Row) -> str:
    return post_day(row["published_at"], row["crawled_at"]) or "未知日期"


def get_options() -> dict:
    with connect() as conn:
        latest = latest_post_date(conn).isoformat()
        sites = [row["name"] for row in conn.execute("SELECT name FROM sites WHERE enabled = 1 ORDER BY name")]
        styles = [
            row["style"]
            for row in conn.execute(
                "SELECT DISTINCT style FROM watch_targets WHERE enabled = 1 ORDER BY style"
            )
            if row["style"]
        ]
        authors = [
            {
                "site": row["site_name"],
                "name": row["display_name"],
                "style": row["style"],
                "value": f"{row['site_name']} / {row['display_name']}",
            }
            for row in conn.execute(
                """
                SELECT sites.name AS site_name, watch_targets.display_name, watch_targets.style
                FROM watch_targets
                JOIN sites ON sites.id = watch_targets.site_id
                WHERE watch_targets.enabled = 1 AND sites.enabled = 1
                ORDER BY sites.name, watch_targets.display_name
                """
            )
        ]
        marked_count = marked_post_count(conn)
        earliest = min_post_date(conn)
    return {
        "sites": sites,
        "styles": styles,
        "authors": authors,
        "latest_date": latest,
        "today_date": date.today().isoformat(),
        "earliest_date": earliest,
        "marked_count": marked_count,
        "db_path": str(DB_PATH),
    }


def get_posts(params: dict[str, list[str]]) -> dict:
    preset = (params.get("preset") or ["recent7"])[0]
    start = (params.get("start") or [""])[0]
    end = (params.get("end") or [""])[0]
    site = (params.get("site") or [""])[0]
    style = (params.get("style") or [""])[0]
    author = (params.get("author") or [""])[0]
    query = (params.get("q") or [""])[0].strip()
    include_noise = (params.get("include_noise") or ["0"])[0] == "1"
    limit = int((params.get("limit") or ["1000"])[0] or 1000)

    with connect() as conn:
        start_date, end_date, label = resolve_date_range(conn, preset, start, end)
        clauses = ["watch_targets.enabled = 1", "sites.enabled = 1"]
        values: list[str] = []
        if not include_noise:
            clauses.append("COALESCE(post_marks.noise, 0) = 0")
        for bad_text in (
            "ERROR:2048",
            "服务器忙",
            "帐号权限不足",
            "账号权限不足",
            "帖子发布或回复时间超过限制",
        ):
            clauses.append("posts.title NOT LIKE ? AND posts.content NOT LIKE ?")
            values.extend([f"%{bad_text}%", f"%{bad_text}%"])
        date_expr = "post_day(posts.published_at, posts.crawled_at)"
        clauses.append(f"{date_expr} BETWEEN ? AND ?")
        values.extend([start_date, end_date])
        if site:
            clauses.append("sites.name = ?")
            values.append(site)
        if style:
            clauses.append("watch_targets.style = ?")
            values.append(style)
        if author:
            site_name, _, author_name = author.partition(" / ")
            clauses.append("sites.name = ? AND watch_targets.display_name = ?")
            values.extend([site_name, author_name])
        if query:
            clauses.append("(posts.title LIKE ? OR posts.content LIKE ?)")
            values.extend([f"%{query}%", f"%{query}%"])

        if preset == "today":
            order_clause = """
                posts.target_id ASC,
                CASE
                    WHEN sites.site_type = 'nga'
                    THEN CAST(COALESCE(NULLIF(json_extract(posts.raw_json, '$.page'), ''), '1') AS INTEGER)
                    ELSE 0
                END ASC,
                CASE
                    WHEN sites.site_type = 'nga' THEN posts.id
                    ELSE 0
                END ASC,
                CASE
                    WHEN sites.site_type <> 'nga' THEN COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at)
                    ELSE ''
                END DESC,
                posts.id ASC
            """
        else:
            order_clause = f"""
                {date_expr} DESC,
                COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at) DESC,
                posts.id ASC
            """

        sql = f"""
            SELECT
                posts.id,
                posts.url,
                posts.title,
                posts.content,
                posts.published_at,
                posts.crawled_at,
                posts.raw_json,
                sites.name AS site_name,
                sites.site_type,
                watch_targets.display_name AS target_name,
                watch_targets.style
            FROM posts
            JOIN sites ON sites.id = posts.site_id
            JOIN watch_targets ON watch_targets.id = posts.target_id
            LEFT JOIN post_marks ON post_marks.post_id = posts.id
            WHERE {' AND '.join(clauses)}
            ORDER BY {order_clause}
            LIMIT ?
        """
        values.append(str(limit))
        rows = list(conn.execute(sql, values))
        marks = get_mark_map(conn, [int(row["id"]) for row in rows])

    posts = []
    author_counts: dict[str, int] = {}
    site_counts: dict[str, int] = {}
    style_counts: dict[str, int] = {}
    useful_count = 0
    for row in rows:
        mark = marks.get(int(row["id"]), mark_from_row(None))
        if mark.get("useful"):
            useful_count += 1
        source = f"{row['site_name']} / {row['target_name']}"
        author_counts[source] = author_counts.get(source, 0) + 1
        site_counts[row["site_name"]] = site_counts.get(row["site_name"], 0) + 1
        style_name = row["style"] or "未分类"
        style_counts[style_name] = style_counts.get(style_name, 0) + 1
        posts.append(
            {
                "id": row["id"],
                "site": row["site_name"],
                "style": style_name,
                "author": row_author(row),
                "source": source,
                "date": post_date(row),
                "published_at": post_time_label(row["published_at"], row["crawled_at"]),
                "title": row["title"] or "",
                "content": row["content"] or "",
                "reply_chain": reply_chain_from_raw(row["raw_json"]),
                "url": row["url"] or "",
                "mark": mark,
            }
        )

    return {
        "range": {"preset": preset, "start": start_date, "end": end_date, "label": label},
        "count": len(posts),
        "posts": posts,
        "author_counts": author_counts,
        "site_counts": site_counts,
        "style_counts": style_counts,
        "useful_count": useful_count,
    }


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>高手发言阅读看板</title>
  <style>
    :root {
      --bg:#f5f6f2; --panel:#fff; --ink:#20242a; --muted:#66717f; --line:#dfe4e8;
      --accent:#1f6feb; --soft:#eaf2ff; --green:#2f7d57; --red:#b54708;
    }
    *{box-sizing:border-box} html{scroll-behavior:smooth}
    body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",Arial,sans-serif;line-height:1.7}
    aside{position:fixed;inset:0 auto 0 0;width:360px;overflow:hidden;background:#fbfcfa;border-right:1px solid var(--line);padding:18px;display:flex;flex-direction:column}
    main{margin-left:360px;padding:22px 34px 72px}
    h1{font-size:22px;margin:0 0 4px}
    .sub{font-size:12px;color:var(--muted);margin-bottom:14px}
    .controls{display:grid;gap:10px;flex:0 0 auto}
    .preset-row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    label{display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px}
    select,input,button{width:100%;height:36px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink);padding:0 9px;font-size:14px}
    button{cursor:pointer;font-weight:700}
    .primary{background:var(--accent);border-color:var(--accent);color:#fff}
    .preset.active{border-color:var(--accent);background:var(--soft);color:#0b4fb3}
    .nav-title{font-size:13px;color:var(--muted);font-weight:800;margin:16px 0 8px;flex:0 0 auto}
    .author-nav{display:grid;gap:7px;overflow-y:auto;min-height:0;flex:1;padding-right:4px}
    .author-nav a{display:block;padding:8px 9px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink);text-decoration:none;font-size:13px}
    .author-nav a:hover{border-color:var(--accent);background:var(--soft)}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:16px;border-bottom:1px solid var(--line);padding-bottom:14px}
    .top h2{margin:0;font-size:28px}.top p{margin:3px 0 0;color:var(--muted)}
    .toolbar{display:flex;gap:8px;flex-wrap:wrap}
    .chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 10px;font-size:12px;color:var(--muted)}
    .group{margin:22px 0 10px;font-size:20px}
    .post{background:#fff;border:1px solid var(--line);border-radius:8px;margin:0 0 14px;padding:16px 18px}
    .post.dim{opacity:.52}
    .meta{display:flex;flex-wrap:wrap;gap:7px 12px;color:var(--muted);font-size:12px;margin-bottom:8px}
    .meta a{color:var(--accent);text-decoration:none}
    .title{font-weight:800;color:#12392b;margin:4px 0 8px}
    .content{white-space:pre-wrap;font-size:16px}
    .reply-context{margin:12px 0;padding:10px 12px;border-left:3px solid #aab7c4;background:#f7f9fb;color:#506070}
    .reply-context-title{margin-bottom:6px;font-size:12px;font-weight:800;color:#718096}
    .reply-item{white-space:pre-wrap;font-size:13px;line-height:1.65}
    .reply-item + .reply-item{margin-top:8px;padding-top:8px;border-top:1px solid #e2e8ef}
    .reply-author{font-weight:700;color:#556575}
    .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
    .actions button{width:auto;height:30px;font-size:12px;padding:0 10px}
    .mark-button{border-color:#dde3ea;background:#f8fafc;color:#8a96a3}
    .mini-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0 0;flex:0 0 auto}
    .mini-stats div{background:#fff;border:1px solid var(--line);border-radius:8px;padding:9px 10px}
    .mini-stats b{display:block;font-size:20px;line-height:1.2}.mini-stats span{font-size:12px;color:var(--muted)}
    .active-tag{border-color:var(--accent);background:var(--soft);color:#0b4fb3}
    .noise{border-color:#ead8d0;background:#fff8f5;color:var(--red)}
    .useful{border-color:#d5eadf;background:#f4fbf7;color:var(--green)}
    .empty{background:#fff;border:1px dashed var(--line);border-radius:8px;padding:28px;color:var(--muted)}
    @media(max-width:900px){aside{position:static;width:auto;border-right:0;border-bottom:1px solid var(--line)}main{margin-left:0;padding:18px}.top{display:block}.top h2{font-size:23px}}
  </style>
</head>
<body>
<aside>
  <h1>高手发言阅读看板</h1>
  <div class="sub" id="sub">读取本地数据库中...</div>
  <div class="controls">
    <div class="preset-row">
      <button class="preset active" data-preset="today">今天</button>
      <button class="preset" data-preset="recent7">最近7天</button>
      <button class="preset" data-preset="weekend">最近3天</button>
      <button class="preset" data-preset="all">全部</button>
    </div>
    <div class="row">
      <div><label>开始</label><input type="date" id="start"></div>
      <div><label>结束</label><input type="date" id="end"></div>
    </div>
    <div class="row">
      <div><label>网站</label><select id="site"><option value="">全部</option></select></div>
      <div><label>分类</label><select id="style"><option value="">全部</option></select></div>
    </div>
    <div><label>关键词</label><input id="q" placeholder="题材、股票、情绪、竞价..."></div>
    <div><button class="primary" id="apply">刷新内容</button></div>
  </div>
  <div class="mini-stats">
    <div><b id="totalCount">0</b><span>总发言</span></div>
    <div><b id="usefulCount">0</b><span>有用</span></div>
  </div>
  <div class="nav-title">作者导航</div>
  <nav class="author-nav" id="authorNav"></nav>
</aside>
<main>
  <div class="top">
    <div><h2 id="title">阅读区</h2><p id="range">等待加载...</p></div>
    <div class="toolbar" id="chips"></div>
  </div>
  <section id="posts"></section>
</main>
<script>
const $ = id => document.getElementById(id);
const state = {preset: 'today', posts: [], options: {}, marks: {}};
function esc(s){
  return String(s || '').replace(/[&<>"']/g, m => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[m]));
}
function markOf(id){ return state.marks[id] || {}; }
function renderReplyChain(chain){
  if (!Array.isArray(chain) || !chain.length) return '';
  const items = chain.map(item => {
    const author = item.author || '\u5f15\u7528\u5185\u5bb9';
    const label = item.time ? `${author} | ${item.time}` : author;
    return `<div class="reply-item"><span class="reply-author">${esc(label)}</span><br>${esc(item.body || '')}</div>`;
  }).join('');
  return `<section class="reply-context"><div class="reply-context-title">\u5f15\u7528\u4e0a\u4e0b\u6587</div>${items}</section>`;
}
function setPreset(preset){
  state.preset = preset;
  document.querySelectorAll('.preset').forEach(btn => btn.classList.toggle('active', btn.dataset.preset === preset));
}
async function setMark(id, key){
  const m = markOf(id);
  const value = !m[key];
  const result = await fetch('/api/mark', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({post_id: id, key, value})
  }).then(r => r.json());
  state.marks[id] = result.mark;
  renderPosts();
}
async function loadOptions(){
  const data = await fetch('/api/options').then(r => r.json());
  state.options = data;
  $('sub').textContent = `最新数据日：${data.latest_date || '-'} | ${data.db_path}`;
  $('start').value = data.today_date || data.latest_date || '';
  $('end').value = data.today_date || data.latest_date || '';
  data.sites.forEach(v => $('site').insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
  data.styles.forEach(v => $('style').insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
}
function params(){
  const p = new URLSearchParams();
  p.set('preset', state.preset);
  if (state.preset === 'custom') {
    p.set('start', $('start').value);
    p.set('end', $('end').value);
  }
  ['site','style','q'].forEach(id => { if ($(id).value) p.set(id, $(id).value); });
  return p;
}
async function loadPosts(){
  const data = await fetch('/api/posts?' + params()).then(r => r.json());
  state.posts = data.posts;
  state.marks = {};
  state.posts.forEach(post => { state.marks[post.id] = post.mark || {}; });
  $('totalCount').textContent = data.count;
  $('usefulCount').textContent = data.useful_count || 0;
  $('title').textContent = '阅读区';
  $('range').textContent = `${data.range.label} | ${data.range.start} 至 ${data.range.end} | ${data.count} 条`;
  $('chips').innerHTML = Object.entries(data.site_counts).map(([k,v])=>`<span class="chip">${esc(k)} ${v}</span>`).join('') +
    Object.entries(data.style_counts).map(([k,v])=>`<span class="chip">${esc(k)} ${v}</span>`).join('');
  renderNav(data.author_counts);
  renderPosts();
}
function renderNav(counts){
  $('authorNav').innerHTML = Object.entries(counts)
    .map(([name,count]) => `<a href="#${esc(anchor(name))}">${esc(name)} (${count})</a>`).join('');
}
function anchor(name){ return 'a-' + name.replace(/[^\w\u4e00-\u9fa5]+/g,'-'); }
function renderPosts(){
  const root = $('posts');
  root.innerHTML = '';
  if (!state.posts.length) {
    root.innerHTML = '<div class="empty">当前条件下没有发言。可以切到最近7天或全部，再试一次。</div>';
    return;
  }
  const seenSources = new Set();
  let previousSource = '';
  for (const p of state.posts) {
    if (p.source !== previousSource) {
      const idAttr = seenSources.has(p.source) ? '' : ` id="${esc(anchor(p.source))}"`;
      root.insertAdjacentHTML('beforeend', `<h3 class="group"${idAttr}>${esc(p.source)}</h3>`);
      seenSources.add(p.source);
      previousSource = p.source;
    }
      const m = markOf(p.id);
      const cls = m.noise ? 'post dim' : 'post';
      root.insertAdjacentHTML('beforeend', `<article class="${cls}">
        <div class="meta"><span>${esc(p.published_at)}</span><span>${esc(p.site)}</span><span>${esc(p.style)}</span><span>${esc(p.author)}</span>${p.url ? `<a target="_blank" rel="noopener" href="${esc(p.url)}">查看原帖</a>`:''}</div>
        ${p.title ? `<div class="title">${esc(p.title)}</div>`:''}
        ${renderReplyChain(p.reply_chain)}
        <div class="content">${esc(p.content)}</div>
        <div class="actions">
          <button onclick="setMark(${p.id}, 'useful')" class="${m.useful?'active-tag useful':'mark-button'}">有用</button>
          <button onclick="setMark(${p.id}, 'noise')" class="${m.noise?'active-tag noise':'mark-button'}">噪音</button>
        </div>
      </article>`);
  }
}
document.querySelectorAll('.preset').forEach(btn => btn.addEventListener('click', () => {
  setPreset(btn.dataset.preset);
  if (state.preset !== 'custom') loadPosts();
}));
$('apply').addEventListener('click', () => { state.preset = 'custom'; setPreset('custom'); loadPosts(); });
['site','style'].forEach(id => $(id).addEventListener('change', loadPosts));
$('q').addEventListener('keydown', e => { if(e.key === 'Enter') loadPosts(); });
loadOptions().then(() => loadPosts());
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/options":
            self.send_json(get_options())
        elif parsed.path == "/api/posts":
            self.send_json(get_posts(parse_qs(parsed.query)))
        elif parsed.path == "/health":
            self.send_json({"ok": True, "time": now_iso()})
        elif parsed.path in {"/", "/index.html"}:
            self.send_html()
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/mark":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json_body()
            post_id = int(payload.get("post_id"))
            key = str(payload.get("key") or "")
            value = bool(payload.get("value"))
            mark = set_post_mark(post_id, key, value)
            with connect() as conn:
                count = marked_post_count(conn)
            self.send_json({"ok": True, "post_id": post_id, "mark": mark, "marked_count": count})
        except Exception as exc:
            self.send_response(HTTPStatus.BAD_REQUEST)
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="本地高手发言阅读看板服务。")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"找不到数据库：{DB_PATH}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"高手发言阅读看板已启动：{url}")
    print(f"数据库：{DB_PATH}")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
