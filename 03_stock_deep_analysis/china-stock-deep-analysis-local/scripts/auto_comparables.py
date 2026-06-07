#!/usr/bin/env python3
"""Auto-build peer comparison rows for China stock dashboards.

This module deliberately does not call LLMs. It selects a conservative peer set
from curated A-share/HK/ADR universes, fetches each peer through fetch_a_share.py,
and converts live quote + F10 finance into render_dashboard.py-compatible rows.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
FETCH = SCRIPT_DIR / "fetch_a_share.py"


def _f(x: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if x is None or x == "" or str(x).lower() in {"nan", "none", "null", "-"}:
            return default
        v = float(str(x).replace(",", "").replace("%", ""))
        return default if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return default


def _quote(raw: Dict[str, Any]) -> Dict[str, Any]:
    qt = raw.get("quote_tencent") or {}
    qs = raw.get("quote_sina") or {}
    qy = raw.get("quote_yahoo") or {}
    primary = qt or qs or qy
    q = dict(primary)
    for src in (qt, qs, qy):
        for k, v in src.items():
            q.setdefault(k, v)
    q["price"] = q.get("price") or qt.get("price") or qs.get("price") or qy.get("price")
    q["pct"] = q.get("pct") or qt.get("pct") or qs.get("pct") or qy.get("pct")
    return q


def _industry_text(raw: Dict[str, Any], dash: Optional[Dict[str, Any]] = None) -> str:
    q = _quote(raw)
    parts = [
        str((dash or {}).get("industry") or ""),
        str((dash or {}).get("title") or ""),
        str(q.get("name") or ""),
        " ".join(str(x) for x in ((dash or {}).get("summary") or [])),
    ]
    return " ".join(parts).lower()


# Curated peer universes. These are candidates only; every selected peer is
# fetched live before entering the dashboard, so stale/static numbers are never
# shown as current data.
PEER_UNIVERSE: Dict[str, List[Dict[str, str]]] = {
    "digital_marketing": [
        {"code": "300058", "name": "蓝色光标", "scene": "AI营销/出海广告龙头弹性"},
        {"code": "002400", "name": "省广集团", "scene": "国资广告营销/低市值对比"},
        {"code": "300781", "name": "因赛集团", "scene": "品牌营销/AI应用小市值弹性"},
        {"code": "603598", "name": "引力传媒", "scene": "内容营销/短剧题材弹性"},
        {"code": "002027", "name": "分众传媒", "scene": "线下广告龙头/现金流与分红对照"},
        {"code": "300063", "name": "天龙集团", "scene": "数字营销/小市值高波动"},
    ],
    "broker": [
        {"code": "600030", "name": "中信证券", "scene": "券商龙头/稳健对照"},
        {"code": "601688", "name": "华泰证券", "scene": "财富管理/低估值对照"},
        {"code": "300059", "name": "东方财富", "scene": "互联网券商/成长弹性"},
        {"code": "601211", "name": "国泰海通", "scene": "头部券商/并购整合"},
    ],
    "bank": [
        {"code": "600036", "name": "招商银行", "scene": "零售银行龙头"},
        {"code": "601166", "name": "兴业银行", "scene": "股份行估值对照"},
        {"code": "601398", "name": "工商银行", "scene": "高股息防守"},
        {"code": "601328", "name": "交通银行", "scene": "低PB/高股息"},
    ],
    "technology": [
        {"code": "300496", "name": "中科创达", "scene": "智能软件/AI终端"},
        {"code": "688111", "name": "金山办公", "scene": "软件SaaS/AI办公"},
        {"code": "300033", "name": "同花顺", "scene": "金融IT/AI应用"},
        {"code": "002230", "name": "科大讯飞", "scene": "AI大模型/应用落地"},
    ],
    "manufacturing": [
        {"code": "300124", "name": "汇川技术", "scene": "工控龙头/制造业质量标杆"},
        {"code": "000333", "name": "美的集团", "scene": "制造龙头/稳健现金流"},
        {"code": "002050", "name": "三花智控", "scene": "热管理/机器人弹性"},
        {"code": "601100", "name": "恒立液压", "scene": "工程机械核心部件"},
    ],
    "consumer": [
        {"code": "600519", "name": "贵州茅台", "scene": "消费龙头/盈利质量"},
        {"code": "000858", "name": "五粮液", "scene": "白酒估值对照"},
        {"code": "603288", "name": "海天味业", "scene": "调味品龙头"},
        {"code": "600887", "name": "伊利股份", "scene": "乳制品/分红防守"},
    ],
    "pharma": [
        {"code": "600276", "name": "恒瑞医药", "scene": "创新药龙头"},
        {"code": "300760", "name": "迈瑞医疗", "scene": "医疗器械龙头"},
        {"code": "000538", "name": "云南白药", "scene": "品牌中药/稳健"},
        {"code": "300015", "name": "爱尔眼科", "scene": "医疗服务弹性"},
    ],
}


def classify_peer_bucket(raw: Dict[str, Any], dash: Optional[Dict[str, Any]] = None) -> str:
    text = _industry_text(raw, dash)
    if any(k in text for k in ["利欧", "蓝色光标", "省广", "因赛", "引力", "分众", "数字营销", "营销", "广告", "传媒", "短剧"]):
        return "digital_marketing"
    if any(k in text for k in ["证券", "券商", "broker"]):
        return "broker"
    if "银行" in text or "bank" in text:
        return "bank"
    if any(k in text for k in ["医药", "医疗", "pharma", "药"]):
        return "pharma"
    if any(k in text for k in ["消费", "食品", "饮料", "白酒", "零售"]):
        return "consumer"
    if any(k in text for k in ["制造", "设备", "机械", "汽车", "新能源", "电池", "光伏", "工业"]):
        return "manufacturing"
    if any(k in text for k in ["科技", "软件", "ai", "人工智能", "互联网", "半导体", "芯片", "数据"]):
        return "technology"
    return "technology"


# Robust override: classify by code/name/industry using clean keywords.
def classify_peer_bucket(raw: Dict[str, Any], dash: Optional[Dict[str, Any]] = None) -> str:
    secu = str(raw.get("secucode") or raw.get("symbol") or (dash or {}).get("code") or "")
    digits = "".join(ch for ch in secu if ch.isdigit())
    if digits in {"002709", "002463"}:
        return "manufacturing"

    text = _industry_text(raw, dash)
    if any(k in text for k in ["\u8bc1\u5238", "\u5238\u5546", "broker"]):
        return "broker"
    if any(k in text for k in ["\u94f6\u884c", "bank"]):
        return "bank"
    if any(k in text for k in ["\u533b\u836f", "\u533b\u7597", "pharma"]):
        return "pharma"
    if any(k in text for k in ["\u6d88\u8d39", "\u98df\u54c1", "\u996e\u6599", "\u767d\u9152", "consumer"]):
        return "consumer"
    if any(k in text for k in ["\u5236\u9020", "\u6750\u6599", "\u5316\u5de5", "\u7535\u89e3\u6db2", "\u9502\u7535", "\u7535\u6c60", "\u65b0\u80fd\u6e90", "pcb", "\u7535\u5b50", "\u8bbe\u5907", "\u673a\u68b0", "\u5de5\u4e1a", "automation"]):
        return "manufacturing"
    if any(k in text for k in ["\u79d1\u6280", "\u8f6f\u4ef6", "ai", "\u4e92\u8054\u7f51", "\u534a\u5bfc\u4f53", "\u82af\u7247", "\u6570\u636e"]):
        return "technology"
    return "technology"


def fetch_peer(code: str, cache_dir: Path, kline_days: int = 80) -> Dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"peer_{code}.json"
    cmd = [sys.executable, str(FETCH), "--code", code, "--out", str(out), "--kline-days", str(kline_days)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=90)
    return json.loads(out.read_text(encoding="utf-8"))


def peer_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    q = _quote(raw)
    f = (raw.get("finance") or [{}])[0]
    price = _f(q.get("price"))
    bps = _f(f.get("BPS"))
    pb = round(price / bps, 2) if price is not None and bps else None
    pe = _f(q.get("pe"))
    rev_yoy = _f(f.get("TOTALOPERATEREVETZ"))
    np_yoy = _f(f.get("PARENTNETPROFITTZ"))
    roe = _f(f.get("ROEJQ"))
    gross = _f(f.get("XSMLL"))
    ocf = _f(f.get("NETCASH_OPERATE_PK"))
    mcap = _f(q.get("mktcap_yi") or q.get("circ_mktcap_yi"))
    amount = _f(q.get("amount"))
    # Tencent A-share amount is often in 万元; leave as source value for display only.
    return {"q": q, "f": f, "price": price, "pe": pe, "pb": pb, "rev_yoy": rev_yoy, "np_yoy": np_yoy, "roe": roe, "gross": gross, "ocf": ocf, "mcap": mcap, "amount": amount}


def score_peer(m: Dict[str, Any]) -> float:
    score = 5.0
    rev = m.get("rev_yoy") or 0
    npy = m.get("np_yoy") or 0
    roe = m.get("roe") or 0
    pb = m.get("pb")
    pe = m.get("pe")
    ocf = m.get("ocf")
    if rev > 20: score += 0.7
    elif rev < 0: score -= 0.5
    if npy > 30: score += 1.0
    elif npy > 0: score += 0.4
    elif npy < 0: score -= 0.8
    if roe > 5: score += 0.7
    elif roe < 1: score -= 0.5
    if ocf is not None and ocf > 0: score += 0.5
    elif ocf is not None and ocf < 0: score -= 0.4
    if pe is not None:
        if 0 < pe < 35: score += 0.4
        elif pe <= 0 or pe > 100: score -= 0.5
    if pb is not None:
        if pb < 3: score += 0.3
        elif pb > 10: score -= 0.6
    return round(max(1, min(9.5, score)), 1)


def _fmt(v: Any, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".")
    else:
        s = str(v)
    return s + suffix


def _load_sub_industry_map() -> Dict[str, Dict[str, str]]:
    p = SCRIPT_DIR.parent / "references" / "a_share_industry_map_20260529.csv"
    out: Dict[str, Dict[str, str]] = {}
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = "".join(ch for ch in str(row.get("code", "")) if ch.isdigit()).zfill(6)
            if not code:
                continue
            out[code] = {
                "name": str(row.get("name", "")).strip(),
                "sub_industry": str(row.get("sub_industry", "")).strip(),
            }
    return out


def _sub_industry_candidates(current_digits: str, limit: int) -> List[Dict[str, str]]:
    m = _load_sub_industry_map()
    cur = m.get(current_digits)
    if not cur:
        return []
    sub = cur.get("sub_industry", "")
    if not sub:
        return []
    rows: List[Dict[str, str]] = []
    for code, info in m.items():
        if code == current_digits:
            continue
        if info.get("sub_industry", "") == sub:
            rows.append({"code": code, "name": info.get("name", code), "scene": f"同细分行业：{sub}"})
        if len(rows) >= max(limit * 4, 20):
            break
    return rows


def build_rows(raw: Dict[str, Any], dash: Optional[Dict[str, Any]] = None, *, limit: int = 5, cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    current_code = str(raw.get("secucode") or raw.get("symbol") or (dash or {}).get("code") or "")
    current_digits = "".join(ch for ch in current_code[:9] if ch.isdigit())
    bucket = classify_peer_bucket(raw, dash)
    candidates = _sub_industry_candidates(current_digits, limit) or PEER_UNIVERSE.get(bucket, PEER_UNIVERSE["technology"])
    cache = cache_dir or (Path.cwd() / "stock_work" / "auto_peers")
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    for cand in candidates:
        code = cand["code"]
        if current_digits and code == current_digits:
            continue
        try:
            peer_raw = fetch_peer(code, cache)
            m = peer_metrics(peer_raw)
            q = m["q"]
            f = m["f"]
            name = q.get("name") or cand.get("name") or code
            score = score_peer(m)
            adv = []
            risk = []
            if (m.get("np_yoy") or 0) > 0: adv.append(f"净利同比{_fmt(round(m['np_yoy'],2),'%')}")
            elif m.get("np_yoy") is not None: risk.append(f"净利同比{_fmt(round(m['np_yoy'],2),'%')}")
            if (m.get("rev_yoy") or 0) > 15: adv.append(f"营收同比{_fmt(round(m['rev_yoy'],2),'%')}")
            if m.get("ocf") is not None and m["ocf"] > 0: adv.append("经营现金流为正")
            elif m.get("ocf") is not None and m["ocf"] < 0: risk.append("经营现金流为负")
            if m.get("pb") is not None and m["pb"] > 8: risk.append(f"PB偏高({m['pb']})")
            if m.get("pe") is not None and (m["pe"] <= 0 or m["pe"] > 100): risk.append(f"PE异常/偏高({_fmt(round(m['pe'],2))})")
            rows.append({
                "name": name,
                "code": code,
                "price": _fmt(m.get("price"), "元"),
                "valuation": f"PE {_fmt(round(m['pe'],2) if m.get('pe') is not None else None)} / PB {_fmt(m.get('pb'))}",
                "score": str(score),
                "advantage": "；".join(adv[:2]) or cand.get("scene") or "同赛道对照",
                "risk": "；".join(risk[:2]) or "题材波动/估值需跟踪",
                "scene": cand.get("scene", "同行对照"),
                "metrics": {
                    "mktcap_yi": m.get("mcap"), "rev_yoy": m.get("rev_yoy"), "np_yoy": m.get("np_yoy"),
                    "roe": m.get("roe"), "gross_margin": m.get("gross"), "ocf": m.get("ocf"), "pct": q.get("pct"),
                },
                "data_source": "自动拉取：新浪/腾讯/东方财富F10",
            })
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{code} {cand.get('name','')}: {exc}")
        if len(rows) >= limit:
            break
    rows.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    better = [r for r in rows if float(r.get("score") or 0) >= float((dash or {}).get("score") or 0)]
    return {
        "bucket": bucket,
        "comparables": rows,
        "better_choices": better[:3],
        "peer_errors": errors,
        "peer_note": "同行候选来自内置行业股票池；展示数据均已逐只实时拉取行情/F10后生成，非静态填表。",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="raw stock JSON from fetch_a_share.py")
    ap.add_argument("--dashboard", default="", help="optional dashboard JSON for industry/title/score context")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    dash = json.loads(Path(args.dashboard).read_text(encoding="utf-8")) if args.dashboard else None
    result = build_rows(raw, dash, limit=args.limit)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": args.out, "bucket": result["bucket"], "rows": len(result["comparables"]), "errors": len(result["peer_errors"])} , ensure_ascii=False))


if __name__ == "__main__":
    main()
