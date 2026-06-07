#!/usr/bin/env python3
"""Merge a debate JSON object into dashboard JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", required=True)
    ap.add_argument("--debate", required=True)
    ap.add_argument("--out", default="", help="optional output dashboard; default overwrites --dashboard")
    args = ap.parse_args()
    dash_path = Path(args.dashboard)
    debate_path = Path(args.debate)
    out_path = Path(args.out) if args.out else dash_path
    dash = json.loads(dash_path.read_text(encoding="utf-8"))
    debate = json.loads(debate_path.read_text(encoding="utf-8"))
    required = ["votes", "direction", "confidence", "summary", "action", "key_level"]
    missing = [k for k in required if not debate.get(k)]
    if missing:
        raise SystemExit(f"debate missing required fields: {missing}")
    if len(debate.get("votes") or []) != 6:
        raise SystemExit("debate must contain exactly 6 votes")
    dash["debate"] = debate
    out_path.write_text(json.dumps(dash, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "dashboard": str(out_path), "debate": str(debate_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
