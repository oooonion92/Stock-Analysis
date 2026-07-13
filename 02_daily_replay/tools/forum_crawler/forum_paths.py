from __future__ import annotations

from pathlib import Path

from forum_db import DATA_DIR, ROOT


ONEDRIVE_REPLIES_ROOT = Path(r"D:\OneDrive\Stock\Replies collect")

CLOUD_ROOT = ROOT / "02_daily_replay" / "forum_reader"
CLOUD_MARKDOWN_ROOT = ONEDRIVE_REPLIES_ROOT
CLOUD_WATCH_TARGETS = ONEDRIVE_REPLIES_ROOT / "watch_targets.csv"
CLOUD_AUTHORS_ROOT = CLOUD_ROOT / "authors"
CLOUD_RAW_ROOT = CLOUD_ROOT / "raw_jsonl"
CLOUD_REPORTS_ROOT = CLOUD_ROOT / "reports"

LOCAL_WATCH_TARGETS = DATA_DIR / "watch_targets.csv"
