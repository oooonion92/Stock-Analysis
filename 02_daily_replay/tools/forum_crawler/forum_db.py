from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "02_daily_replay" / "data"
DEFAULT_DB_PATH = DATA_DIR / "forum_watchlist.sqlite"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            base_url TEXT NOT NULL,
            site_type TEXT NOT NULL,
            login_required INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watch_targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            display_name TEXT NOT NULL,
            external_user_id TEXT NOT NULL,
            profile_url TEXT NOT NULL DEFAULT '',
            target_type TEXT NOT NULL DEFAULT 'replies',
            style TEXT NOT NULL DEFAULT '未知',
            enabled INTEGER NOT NULL DEFAULT 1,
            crawl_pages INTEGER NOT NULL DEFAULT 3,
            crawl_interval_minutes INTEGER NOT NULL DEFAULT 1440,
            last_crawled_at TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(site_id, external_user_id, target_type)
        );

        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES watch_targets(id) ON DELETE CASCADE,
            external_post_id TEXT NOT NULL DEFAULT '',
            external_thread_id TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '',
            crawled_at TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            raw_json TEXT NOT NULL DEFAULT '{}',
            UNIQUE(site_id, external_post_id),
            UNIQUE(site_id, url),
            UNIQUE(site_id, target_id, content_hash)
        );

        CREATE TABLE IF NOT EXISTS crawl_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            target_id INTEGER NOT NULL REFERENCES watch_targets(id) ON DELETE CASCADE,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            pages_requested INTEGER NOT NULL DEFAULT 0,
            posts_found INTEGER NOT NULL DEFAULT 0,
            posts_new INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_posts_target_time ON posts(target_id, published_at);
        CREATE INDEX IF NOT EXISTS idx_targets_enabled ON watch_targets(enabled);
        """
    )
    ensure_column(conn, "watch_targets", "style", "TEXT NOT NULL DEFAULT '未知'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_targets_style ON watch_targets(style)")
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def upsert_site(
    conn: sqlite3.Connection,
    name: str,
    base_url: str,
    site_type: str,
    login_required: bool = True,
    enabled: bool = True,
    notes: str = "",
) -> int:
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO sites(name, base_url, site_type, login_required, enabled, notes, created_at, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            base_url = excluded.base_url,
            site_type = excluded.site_type,
            login_required = excluded.login_required,
            enabled = excluded.enabled,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (name, base_url, site_type, int(login_required), int(enabled), notes, stamp, stamp),
    )
    conn.commit()
    return int(conn.execute("SELECT id FROM sites WHERE name = ?", (name,)).fetchone()["id"])


def get_site(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM sites WHERE name = ?", (name,)).fetchone()
    if row is None:
        raise SystemExit(f"站点不存在：{name}")
    return row


def upsert_target(
    conn: sqlite3.Connection,
    site_name: str,
    display_name: str,
    external_user_id: str,
    profile_url: str = "",
    target_type: str = "replies",
    style: str = "未知",
    enabled: bool = True,
    crawl_pages: int = 3,
    crawl_interval_minutes: int = 1440,
    notes: str = "",
) -> int:
    site = get_site(conn, site_name)
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO watch_targets(
            site_id, display_name, external_user_id, profile_url, target_type,
            style, enabled, crawl_pages, crawl_interval_minutes, notes, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_id, external_user_id, target_type) DO UPDATE SET
            display_name = excluded.display_name,
            profile_url = excluded.profile_url,
            style = excluded.style,
            enabled = excluded.enabled,
            crawl_pages = excluded.crawl_pages,
            crawl_interval_minutes = excluded.crawl_interval_minutes,
            notes = excluded.notes,
            updated_at = excluded.updated_at
        """,
        (
            int(site["id"]),
            display_name,
            external_user_id,
            profile_url,
            target_type,
            style,
            int(enabled),
            crawl_pages,
            crawl_interval_minutes,
            notes,
            stamp,
            stamp,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM watch_targets WHERE site_id = ? AND external_user_id = ? AND target_type = ?",
        (int(site["id"]), external_user_id, target_type),
    ).fetchone()
    return int(row["id"])


def list_enabled_targets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                watch_targets.*,
                sites.name AS site_name,
                sites.base_url,
                sites.site_type
            FROM watch_targets
            JOIN sites ON sites.id = watch_targets.site_id
            WHERE watch_targets.enabled = 1 AND sites.enabled = 1
            ORDER BY sites.name, watch_targets.display_name
            """
        )
    )


def list_targets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT
                watch_targets.*,
                sites.name AS site_name,
                sites.site_type
            FROM watch_targets
            JOIN sites ON sites.id = watch_targets.site_id
            ORDER BY sites.name, watch_targets.display_name
            """
        )
    )


def content_hash(title: str, content: str) -> str:
    value = f"{title}\n{content}".encode("utf-8", errors="ignore")
    return hashlib.sha256(value).hexdigest()


def insert_posts(
    conn: sqlite3.Connection,
    site_id: int,
    target_id: int,
    records: Iterable[dict[str, Any]],
) -> int:
    inserted = 0
    for record in records:
        title = str(record.get("title") or "")
        content = str(record.get("content") or "")
        if not title and not content:
            continue
        payload = {
            "site_id": site_id,
            "target_id": target_id,
            "external_post_id": str(record.get("post_id") or ""),
            "external_thread_id": str(record.get("thread_id") or ""),
            "url": str(record.get("url") or ""),
            "title": title,
            "content": content,
            "published_at": str(record.get("published_at") or ""),
            "crawled_at": str(record.get("crawl_time") or now_iso()),
            "content_hash": content_hash(title, content),
            "raw_json": json.dumps(record, ensure_ascii=False),
        }
        existing = None
        if payload["external_post_id"]:
            existing = conn.execute(
                "SELECT id FROM posts WHERE site_id = ? AND external_post_id = ?",
                (site_id, payload["external_post_id"]),
            ).fetchone()
        if existing is None and payload["url"]:
            existing = conn.execute(
                "SELECT id FROM posts WHERE site_id = ? AND url = ?",
                (site_id, payload["url"]),
            ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id FROM posts WHERE site_id = ? AND target_id = ? AND content_hash = ?",
                (site_id, target_id, payload["content_hash"]),
            ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO posts(
                    site_id, target_id, external_post_id, external_thread_id, url, title,
                    content, published_at, crawled_at, content_hash, raw_json
                )
                VALUES(
                    :site_id, :target_id, :external_post_id, :external_thread_id, :url, :title,
                    :content, :published_at, :crawled_at, :content_hash, :raw_json
                )
                """,
                payload,
            )
            inserted += 1
        else:
            conn.execute(
                """
                UPDATE posts
                SET
                    external_post_id = :external_post_id,
                    external_thread_id = :external_thread_id,
                    url = :url,
                    title = :title,
                    content = :content,
                    published_at = :published_at,
                    crawled_at = :crawled_at,
                    content_hash = :content_hash,
                    raw_json = :raw_json
                WHERE id = :id
                """,
                {**payload, "id": int(existing["id"])},
            )
    conn.commit()
    return inserted


def start_run(conn: sqlite3.Connection, site_id: int, target_id: int, pages_requested: int) -> int:
    cur = conn.execute(
        """
        INSERT INTO crawl_runs(site_id, target_id, started_at, status, pages_requested)
        VALUES(?, ?, ?, 'running', ?)
        """,
        (site_id, target_id, now_iso(), pages_requested),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    posts_found: int = 0,
    posts_new: int = 0,
    error_message: str = "",
) -> None:
    conn.execute(
        """
        UPDATE crawl_runs
        SET finished_at = ?, status = ?, posts_found = ?, posts_new = ?, error_message = ?
        WHERE id = ?
        """,
        (now_iso(), status, posts_found, posts_new, error_message, run_id),
    )
    conn.commit()


def mark_target_crawled(conn: sqlite3.Connection, target_id: int) -> None:
    conn.execute(
        "UPDATE watch_targets SET last_crawled_at = ?, updated_at = ? WHERE id = ?",
        (now_iso(), now_iso(), target_id),
    )
    conn.commit()


def posts_for_target(conn: sqlite3.Connection, target_id: int, limit: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT * FROM posts
        WHERE target_id = ?
        ORDER BY COALESCE(NULLIF(published_at, ''), crawled_at) DESC, id DESC
    """
    params: tuple[Any, ...] = (target_id,)
    if limit:
        sql += " LIMIT ?"
        params = (target_id, limit)
    return list(conn.execute(sql, params))
