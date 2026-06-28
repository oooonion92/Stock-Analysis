from __future__ import annotations

import argparse
import json
import sqlite3
import webbrowser
from datetime import date, datetime, time, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[3]
DB_PATH = ROOT / "02_daily_replay" / "data" / "forum_watchlist.sqlite"
CLOUD_ROOT = Path(r"D:\OneDrive\Stock\Replies collect")


def parse_time(value: str | None) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def iso_date(value: datetime) -> str:
    return value.date().isoformat()


def date_range(preset: str, start: str = "", end: str = "") -> tuple[str, str, str]:
    today = date.today()
    if preset == "today":
        begin = finish = today
        label = "今天"
    elif preset == "yesterday":
        begin = finish = today - timedelta(days=1)
        label = "昨天"
    elif preset == "weekend":
        days_since_friday = (today.weekday() - 4) % 7
        begin = today - timedelta(days=days_since_friday)
        finish = begin + timedelta(days=2)
        label = "周末包"
    elif preset == "week":
        begin = today - timedelta(days=today.weekday())
        finish = today
        label = "本周"
    elif preset == "custom" and start and end:
        return start, end, f"{start} 至 {end}"
    else:
        begin = today - timedelta(days=2)
        finish = today
        label = "最近3天"
    return begin.isoformat(), finish.isoformat(), label


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_marks_db(conn)
    return conn


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_post_marks_refine ON post_marks(refine)")
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
        "refine": "refine",
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


def post_date(row: sqlite3.Row) -> str:
    parsed = parse_time(row["published_at"] or row["crawled_at"])
    if parsed:
        return parsed.date().isoformat()
    value = str(row["published_at"] or row["crawled_at"] or "")
    return value[:10] if len(value) >= 10 else "未知日期"


def get_options() -> dict:
    with connect() as conn:
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
        latest = conn.execute(
            "SELECT MAX(COALESCE(NULLIF(published_at, ''), crawled_at)) AS latest FROM posts"
        ).fetchone()["latest"]
        marked_count = marked_post_count(conn)
    return {
        "sites": sites,
        "styles": styles,
        "authors": authors,
        "latest": latest or "",
        "marked_count": marked_count,
        "db_path": str(DB_PATH),
        "cloud_root": str(CLOUD_ROOT),
    }


def get_posts(params: dict[str, list[str]]) -> dict:
    preset = (params.get("preset") or ["recent3"])[0]
    start = (params.get("start") or [""])[0]
    end = (params.get("end") or [""])[0]
    site = (params.get("site") or [""])[0]
    style = (params.get("style") or [""])[0]
    author = (params.get("author") or [""])[0]
    query = (params.get("q") or [""])[0].strip()
    unread_after = (params.get("unread_after") or [""])[0].strip()
    mark_filter = (params.get("mark") or [""])[0].strip()
    include_noise = (params.get("include_noise") or ["0"])[0] == "1"
    limit = int((params.get("limit") or ["800"])[0] or 800)
    start_date, end_date, label = date_range(preset, start, end)

    clauses = ["watch_targets.enabled = 1", "sites.enabled = 1"]
    values: list[str] = []
    if not include_noise:
        clauses.append("COALESCE(post_marks.noise, 0) = 0")
    if mark_filter == "useful":
        clauses.append("COALESCE(post_marks.useful, 0) = 1")
    elif mark_filter == "refine":
        clauses.append("COALESCE(post_marks.refine, 0) = 1")
    elif mark_filter == "selected":
        clauses.append("(COALESCE(post_marks.useful, 0) = 1 OR COALESCE(post_marks.refine, 0) = 1)")
    elif mark_filter == "noise":
        clauses.append("COALESCE(post_marks.noise, 0) = 1")
    for bad_text in (
        "ERROR:2048",
        "服务器忙",
        "帐号权限不足",
        "账号权限不足",
        "帖子发布或回复时间超过限制",
    ):
        clauses.append("posts.title NOT LIKE ? AND posts.content NOT LIKE ?")
        values.extend([f"%{bad_text}%", f"%{bad_text}%"])
    if unread_after:
        clauses.append("posts.crawled_at > ?")
        values.append(unread_after)
    else:
        clauses.append("substr(COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at), 1, 10) BETWEEN ? AND ?")
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
        ORDER BY COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at) DESC, posts.id DESC
        LIMIT ?
    """
    values.append(str(limit))

    with connect() as conn:
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
        source = f"{row['site_name']} / {row_author(row)}"
        author_counts[source] = author_counts.get(source, 0) + 1
        site_counts[row["site_name"]] = site_counts.get(row["site_name"], 0) + 1
        style_counts[row["style"] or "未分类"] = style_counts.get(row["style"] or "未分类", 0) + 1
        posts.append(
            {
                "id": row["id"],
                "site": row["site_name"],
                "style": row["style"] or "未分类",
                "author": row_author(row),
                "source": source,
                "date": post_date(row),
                "published_at": row["published_at"] or row["crawled_at"],
                "crawled_at": row["crawled_at"],
                "title": row["title"] or "",
                "content": row["content"] or "",
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
  <title>高手发言阅读中心</title>
  <style>
    :root {
      --bg:#f6f7f4; --panel:#fff; --ink:#20242a; --muted:#66717f; --line:#dfe4e8;
      --accent:#1f6feb; --soft:#eaf2ff; --green:#2f7d57; --red:#b54708; --yellow:#8a6116;
    }
    *{box-sizing:border-box} html{scroll-behavior:smooth}
    body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","PingFang SC","Segoe UI",Arial,sans-serif;line-height:1.7}
    aside{position:fixed;inset:0 auto 0 0;width:360px;overflow:hidden;background:#fbfcfa;border-right:1px solid var(--line);padding:18px;display:flex;flex-direction:column}
    main{margin-left:360px;padding:22px 34px 72px}
    h1{font-size:22px;margin:0 0 4px} .sub{font-size:12px;color:var(--muted);margin-bottom:14px}
    .controls{display:grid;gap:10px;flex:0 0 auto}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    label{display:block;font-size:12px;font-weight:700;color:var(--muted);margin-bottom:4px}
    select,input,button{width:100%;height:36px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink);padding:0 9px;font-size:14px}
    button{cursor:pointer;font-weight:700}.primary{background:var(--accent);border-color:var(--accent);color:#fff}.ghost{background:#fff}
    .nav-title{font-size:13px;color:var(--muted);font-weight:800;margin:16px 0 8px;flex:0 0 auto}.author-nav{display:grid;gap:7px;overflow-y:auto;min-height:0;flex:1;padding-right:4px}
    .author-nav a{display:block;padding:8px 9px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink);text-decoration:none;font-size:13px}
    .author-nav a:hover{border-color:var(--accent);background:var(--soft)}
    .top{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:16px;border-bottom:1px solid var(--line);padding-bottom:14px}
    .top h2{margin:0;font-size:28px}.top p{margin:3px 0 0;color:var(--muted)}
    .toolbar{display:flex;gap:8px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 10px;font-size:12px;color:var(--muted)}
    .group{margin:22px 0 10px;font-size:20px}.post{background:#fff;border:1px solid var(--line);border-radius:8px;margin:0 0 14px;padding:16px 18px}
    .post.dim{opacity:.52}.meta{display:flex;flex-wrap:wrap;gap:7px 12px;color:var(--muted);font-size:12px;margin-bottom:8px}
    .meta a{color:var(--accent);text-decoration:none}.title{font-weight:800;color:#12392b;margin:4px 0 8px}.content{white-space:pre-wrap;font-size:16px}
    .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.actions button{width:auto;height:30px;font-size:12px;padding:0 10px}
    .mark-button{border-color:#dde3ea;background:#f8fafc;color:#8a96a3}
    .mini-stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0 0;flex:0 0 auto}
    .mini-stats div{background:#fff;border:1px solid var(--line);border-radius:8px;padding:9px 10px}
    .mini-stats b{display:block;font-size:20px;line-height:1.2}.mini-stats span{font-size:12px;color:var(--muted)}
    .active-tag{border-color:var(--accent);background:var(--soft);color:#0b4fb3}.noise{border-color:#ead8d0;background:#fff8f5;color:var(--red)}
    .useful{border-color:#d5eadf;background:#f4fbf7;color:var(--green)}.refine{border-color:#eadfab;background:#fffaf0;color:var(--yellow)}
    .empty{background:#fff;border:1px dashed var(--line);border-radius:8px;padding:28px;color:var(--muted)}
    @media(max-width:900px){aside{position:static;width:auto;border-right:0;border-bottom:1px solid var(--line)}main{margin-left:0;padding:18px}.top{display:block}.top h2{font-size:23px}}
  </style>
</head>
<body>
<aside>
  <h1>高手发言阅读中心</h1>
  <div class="sub" id="sub">读取本地数据库，不抓取网站</div>
  <div class="controls">
    <div class="row">
      <div><label>开始</label><input type="date" id="start"></div>
      <div><label>结束</label><input type="date" id="end"></div>
    </div>
    <div class="row">
      <div><label>网站</label><select id="site"><option value="">全部</option></select></div>
      <div><label>分类</label><select id="style"><option value="">全部</option></select></div>
    </div>
    <div><label>关键词</label><input id="q" placeholder="题材、股票、情绪、竞价..."></div>
    <div>
      <button class="primary" id="apply">应用筛选</button>
    </div>
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
    <div><h2 id="title">阅读区</h2><p id="range">请选择筛选条件</p></div>
    <div class="toolbar" id="chips"></div>
  </div>
  <section id="posts"></section>
</main>
<script>
const $ = id => document.getElementById(id);
const state = {posts: [], options: {}, marks: {}};
function saveMarks(){ updateMarked(); }
function esc(s){ return String(s||'').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
function markOf(id){ return state.marks[id] || {}; }
async function setMark(id, key){
  const m = markOf(id);
  const value = !m[key];
  const result = await fetch('/api/mark', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({post_id: id, key, value})
  }).then(r => r.json());
  state.marks[id] = result.mark;
  state.options.marked_count = result.marked_count;
  saveMarks(); renderPosts();
}
function updateMarked(){}
async function loadOptions(){
  const data = await fetch('/api/options').then(r=>r.json()); state.options = data;
  $('sub').textContent = `最新入库：${data.latest || '-'} · ${data.db_path}`;
  data.sites.forEach(v => $('site').insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
  data.styles.forEach(v => $('style').insertAdjacentHTML('beforeend', `<option value="${esc(v)}">${esc(v)}</option>`));
  setDefaultDates();
  updateMarked();
}
function setDefaultDates(){
  if ($('start').value && $('end').value) return;
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - 2);
  $('start').value = start.toISOString().slice(0, 10);
  $('end').value = end.toISOString().slice(0, 10);
}
function params(){
  const p = new URLSearchParams();
  p.set('preset', 'custom');
  p.set('start', $('start').value);
  p.set('end', $('end').value);
  ['site','style','q'].forEach(id => { if ($(id).value) p.set(id, $(id).value); });
  return p;
}
async function loadPosts(){
  const data = await fetch('/api/posts?' + params()).then(r=>r.json()); state.posts = data.posts;
  state.marks = {};
  state.posts.forEach(post => { state.marks[post.id] = post.mark || {}; });
  $('totalCount').textContent = data.count;
  $('usefulCount').textContent = data.useful_count || 0;
  $('title').textContent = '阅读区';
  $('range').textContent = `${data.range.start} 至 ${data.range.end} · ${data.count} 条`;
  $('chips').innerHTML = Object.entries(data.site_counts).map(([k,v])=>`<span class="chip">${esc(k)} ${v}</span>`).join('') +
    Object.entries(data.style_counts).map(([k,v])=>`<span class="chip">${esc(k)} ${v}</span>`).join('');
  renderNav(data.author_counts); renderPosts();
}
function renderNav(counts){
  $('authorNav').innerHTML = Object.entries(counts).sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0]))
    .map(([name,count]) => `<a href="#${esc(anchor(name))}">${esc(name)} (${count})</a>`).join('');
}
function anchor(name){ return 'a-' + name.replace(/[^\w\u4e00-\u9fa5]+/g,'-'); }
function renderPosts(){
  const root = $('posts'); root.innerHTML = '';
  if (!state.posts.length) { root.innerHTML = '<div class="empty">当前条件下没有发言。可以换一个日期模式或清空作者/关键词筛选。</div>'; return; }
  const groups = new Map();
  for (const p of state.posts) {
    if (!groups.has(p.source)) groups.set(p.source, []);
    groups.get(p.source).push(p);
  }
  const orderedGroups = Array.from(groups.entries()).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
  for (const [source, posts] of orderedGroups){
    root.insertAdjacentHTML('beforeend', `<h3 class="group" id="${esc(anchor(source))}">${esc(source)}</h3>`);
    for (const p of posts) {
    const m = markOf(p.id); const cls = m.noise ? 'post dim' : 'post';
    root.insertAdjacentHTML('beforeend', `<article class="${cls}">
      <div class="meta"><span>${esc(p.published_at)}</span><span>${esc(p.date)}</span><span>${esc(p.site)}</span><span>${esc(p.style)}</span><span>${esc(p.author)}</span>${p.url ? `<a target="_blank" rel="noopener" href="${esc(p.url)}">查看原帖</a>`:''}</div>
      ${p.title ? `<div class="title">${esc(p.title)}</div>`:''}
      <div class="content">${esc(p.content)}</div>
      <div class="actions">
        <button onclick="setMark(${p.id}, 'useful')" class="${m.useful?'active-tag useful':'mark-button'}">有用</button>
        <button onclick="setMark(${p.id}, 'noise')" class="${m.noise?'active-tag noise':'mark-button'}">噪音</button>
      </div>
    </article>`);
    }
  }
  updateMarked();
}
$('apply').addEventListener('click', loadPosts);
['start','end','site','style'].forEach(id => $(id).addEventListener('change', loadPosts));
$('q').addEventListener('keydown', e => { if(e.key === 'Enter') loadPosts(); });
loadOptions().then(loadPosts);
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
    parser = argparse.ArgumentParser(description="本地高手发言阅读中心，只读数据库，不抓取网站。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"找不到数据库：{DB_PATH}")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"高手发言阅读中心已启动：{url}")
    print(f"数据库：{DB_PATH}")
    print("这个工具只读取本地数据，不会抓取网站。关闭窗口即可停止。")
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
