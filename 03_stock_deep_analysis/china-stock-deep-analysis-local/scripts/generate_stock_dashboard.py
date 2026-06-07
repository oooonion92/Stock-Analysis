#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

SCRIPT_DIR = Path(__file__).resolve().parent
FETCH = SCRIPT_DIR / "fetch_a_share.py"
SCORING = SCRIPT_DIR / "scoring_model.py"
PEERS = SCRIPT_DIR / "auto_comparables.py"
DEBATE = SCRIPT_DIR / "debate_engine.py"
RENDER = SCRIPT_DIR / "render_dashboard.py"


def run(cmd: List[str], *, timeout: int = 240) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(
            f"command failed ({p.returncode}): {' '.join(cmd)}\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}"
        )
    return p


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def code_slug(code: str) -> str:
    raw = str(code).strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits or re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def merge_peer_summary(dash: Dict[str, Any], peers: Dict[str, Any]) -> None:
    dash["comparables"] = peers.get("comparables") or []
    dash["better_choices"] = peers.get("better_choices") or []
    dash["peer_note"] = peers.get("peer_note")
    dash["peer_bucket"] = peers.get("bucket")
    dash["peer_errors"] = peers.get("peer_errors") or []
    valuation = dash.get("valuation") or {}
    comps = valuation.get("comps_valuation") or {}
    comps["peer_context"] = f"已拉取{len(dash['comparables'])}个同行样本；更优候选{len(dash['better_choices'])}个；错误{len(dash['peer_errors'])}条。"
    comps["rows"] = dash["comparables"]
    valuation["comps_valuation"] = comps
    dash["valuation"] = valuation


def validate_dashboard(dash: Dict[str, Any], *, quick: bool, no_debate: bool) -> List[str]:
    issues: List[str] = []
    required = ["title", "code", "score", "summary", "metrics", "kline", "trade_plan", "scores", "risks", "data_sources"]
    required += ["company_tearsheet", "investment_thesis", "catalyst_timeline", "position_view", "thesis_tracker", "valuation"]
    for k in required:
        if not dash.get(k):
            issues.append(f"missing dashboard field: {k}")
    thesis = dash.get("investment_thesis") or {}
    for k in ["core_thesis", "evidence_for", "evidence_against", "what_to_watch"]:
        if not thesis.get(k):
            issues.append(f"missing investment_thesis field: {k}")
    valuation = dash.get("valuation") or {}
    for k in ["method", "comps_valuation", "valuation_range", "scenario_sensitivity", "audit_flags"]:
        if not valuation.get(k):
            issues.append(f"missing valuation field: {k}")
    if not quick and not dash.get("comparables"):
        issues.append("missing comparables")
    if not no_debate:
        debate = dash.get("debate") or {}
        for k in ["votes", "direction", "confidence", "summary", "action", "key_level"]:
            if not debate.get(k):
                issues.append(f"missing debate field: {k}")
    return issues


def validate_html(path: Path) -> List[str]:
    if not path.exists() or path.stat().st_size <= 0:
        return [f"html missing or empty: {path}"]
    html = path.read_text(encoding="utf-8", errors="ignore")
    for term in ['id="overview"', 'id="kline"', 'id="finance"', 'id="source"']:
        if term not in html:
            return [f"html missing section: {term}"]
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate complete China stock HTML dashboard")
    ap.add_argument("--code", required=True)
    ap.add_argument("--market", choices=["auto", "a", "hk", "us"], default="auto")
    ap.add_argument("--industry", default="")
    ap.add_argument("--catalyst-score", type=float)
    ap.add_argument("--kline-days", type=int, default=160)
    ap.add_argument("--peer-limit", type=int, default=5)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--with-debate", action="store_true")
    ap.add_argument("--work-dir", default="/root/.openclaw/workspace/stock_work")
    ap.add_argument("--out-dir", default="/root/.openclaw/workspace/outputs")
    ap.add_argument("--date", default=today_yyyymmdd())
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    work = Path(args.work_dir)
    out_dir = Path(args.out_dir)
    work.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    slug = code_slug(args.code)
    raw_path = work / f"{slug}_raw.json"
    dash_path = work / f"{slug}_dash.json"
    peers_path = work / f"{slug}_peers.json"
    debate_path = work / f"{slug}_debate.json"
    html_path = out_dir / f"stock_{slug}_{args.date}.html"

    run(
        [
            sys.executable,
            str(FETCH),
            "--code",
            args.code,
            "--market",
            args.market,
            "--out",
            str(raw_path),
            "--kline-days",
            str(args.kline_days),
        ],
        timeout=240,
    )
    score_cmd = [sys.executable, str(SCORING), "--input", str(raw_path), "--out", str(dash_path)]
    if args.industry:
        score_cmd += ["--industry", args.industry]
    if args.catalyst_score is not None:
        score_cmd += ["--catalyst-score", str(args.catalyst_score)]
    run(score_cmd, timeout=120)
    dash = load_json(dash_path)

    if not args.quick:
        run(
            [
                sys.executable,
                str(PEERS),
                "--input",
                str(raw_path),
                "--dashboard",
                str(dash_path),
                "--out",
                str(peers_path),
                "--limit",
                str(args.peer_limit),
            ],
            timeout=420,
        )
        peers = load_json(peers_path)
        merge_peer_summary(dash, peers)
        save_json(dash_path, dash)

    no_debate = not args.with_debate
    if args.with_debate:
        run([sys.executable, str(DEBATE), "--input", str(dash_path), "--out", str(debate_path)], timeout=420)
        dash = load_json(dash_path)
        dash["debate"] = load_json(debate_path)
        save_json(dash_path, dash)

    issues = validate_dashboard(dash, quick=args.quick, no_debate=no_debate)
    if issues:
        raise RuntimeError("dashboard validation failed:\n" + "\n".join(issues))

    run([sys.executable, str(RENDER), "--input", str(dash_path), "--out-html", str(html_path)], timeout=180)
    html_issues = validate_html(html_path)
    if html_issues:
        raise RuntimeError("html validation failed:\n" + "\n".join(html_issues))

    result = {
        "ok": True,
        "code": args.code,
        "raw": str(raw_path),
        "dashboard": str(dash_path),
        "peers": str(peers_path) if peers_path.exists() else None,
        "debate": str(debate_path) if args.with_debate and debate_path.exists() else None,
        "html": str(html_path),
        "media_line": "MEDIA:" + str(html_path),
        "comparables": len(dash.get("comparables") or []),
        "debate_fallback": bool((dash.get("debate") or {}).get("fallback")),
        "warnings": dash.get("warnings") or [],
        "peer_errors": dash.get("peer_errors") or [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.json else None))


if __name__ == "__main__":
    main()
