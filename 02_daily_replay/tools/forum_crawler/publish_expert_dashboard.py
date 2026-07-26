from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from forum_db import connect


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DASHBOARD_REPO = PROJECT_ROOT.parent / "Stock-Replay-Dashboard"
DASHBOARD_REMOTE = "https://github.com/oooonion92/Stock-Replay-Dashboard.git"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def parse_time(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def stable_id(row, body: str) -> str:
    source = str(row["site_name"] or "source").lower()
    external_id = str(row["external_post_id"] or "").strip()
    if external_id:
        return f"{source}-{external_id}"
    url = str(row["url"] or "").strip()
    seed = url or "|".join((source, str(row["author"] or ""), str(row["published_at"] or ""), body))
    return f"{source}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:20]}"


def build_payload(days: int = 7) -> dict:
    now = datetime.now(SHANGHAI)
    start = (now.date() - timedelta(days=days - 1)).isoformat()
    end = now.date().isoformat()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT posts.external_post_id, posts.url, posts.title, posts.content,
                   posts.published_at, posts.crawled_at, sites.name AS site_name,
                   watch_targets.display_name AS author, watch_targets.style AS category
            FROM posts
            JOIN sites ON sites.id = posts.site_id
            JOIN watch_targets ON watch_targets.id = posts.target_id
            WHERE sites.enabled = 1 AND watch_targets.enabled = 1
              AND substr(COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at), 1, 10) BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchall()

    records, seen = [], set()
    for row in rows:
        body = str(row["content"] or "").strip()
        when = parse_time(str(row["published_at"] or row["crawled_at"] or ""))
        if not body or when is None:
            continue
        record_id = stable_id(row, body)
        if record_id in seen:
            continue
        seen.add(record_id)
        records.append({
            "id": record_id,
            "date": when.date().isoformat(),
            "time": when.strftime("%H:%M"),
            "source": str(row["site_name"] or ""),
            "author": str(row["author"] or ""),
            "category": str(row["category"] or ""),
            "topic": str(row["title"] or ""),
            "url": str(row["url"] or ""),
            "body": body,
        })
    records.sort(key=lambda item: (item["date"], item["time"], item["id"]), reverse=True)
    if not records:
        raise RuntimeError("Dashboard payload has no valid records; keeping the previous Pages data.")
    return {
        "source": "collector database",
        "updatedAt": now.isoformat(timespec="seconds"),
        "recordCount": len(records),
        "records": records,
        "schemaVersion": 1,
        "generatedAt": now.isoformat(timespec="seconds"),
        "window": {"timezone": "Asia/Shanghai", "startDate": start, "endDate": end},
    }


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True)


def git_output(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def synchronize_dashboard_repo() -> None:
    """Fast-forward Pages, preserving an obsolete local data-only commit if needed."""
    repo_args = ("-C", str(DASHBOARD_REPO))
    if git_output(*repo_args, "status", "--porcelain"):
        raise RuntimeError(f"Dashboard repository has uncommitted changes: {DASHBOARD_REPO}")

    git(*repo_args, "fetch", "origin")
    ahead, behind = (
        int(value)
        for value in git_output(*repo_args, "rev-list", "--left-right", "--count", "HEAD...origin/main").split()
    )
    if ahead == 0 and behind == 0:
        return
    if ahead == 0:
        git(*repo_args, "merge", "--ff-only", "origin/main")
        return
    if behind == 0:
        return

    merge_base = git_output(*repo_args, "merge-base", "HEAD", "origin/main")
    local_paths = {
        path
        for path in git_output(*repo_args, "diff", "--name-only", f"{merge_base}..HEAD").splitlines()
        if path
    }
    data_path = "experts/experts-data.json"
    if local_paths != {data_path}:
        raise RuntimeError(
            "Dashboard repository diverged from origin/main and local commits modify "
            f"more than {data_path}: {sorted(local_paths)}"
        )

    backup = f"backup/publish-before-sync-{datetime.now(SHANGHAI):%Y%m%d-%H%M%S}"
    git(*repo_args, "branch", backup, "HEAD")
    git(*repo_args, "reset", "--hard", "origin/main")
    print(f"Saved the previous local data commit to {backup} before syncing Pages.")


def publish() -> tuple[Path, int, bool]:
    payload = build_payload()
    if not DASHBOARD_REPO.exists():
        git("clone", DASHBOARD_REMOTE, str(DASHBOARD_REPO))
    synchronize_dashboard_repo()
    target = DASHBOARD_REPO / "experts" / "experts-data.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp, target)
    changed = subprocess.run(["git", "-C", str(DASHBOARD_REPO), "diff", "--quiet", "--", "experts/experts-data.json"]).returncode != 0
    if changed:
        git("-C", str(DASHBOARD_REPO), "add", "experts/experts-data.json")
        git("-C", str(DASHBOARD_REPO), "commit", "-m", f"data: update expert posts {payload['window']['endDate']}")
        git("-C", str(DASHBOARD_REPO), "push", "origin", "HEAD")
    return target, payload["recordCount"], changed


def main() -> int:
    target, count, changed = publish()
    action = "Published" if changed else "Already up to date"
    print(f"{action}: {count} records -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
