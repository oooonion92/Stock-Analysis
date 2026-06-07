#!/usr/bin/env python3
"""Fetch market/quote/kline/fundamental snapshots for China-related equities.

Backward compatible with the old CLI:
  fetch_a_share.py --code 600030 --out raw.json

New:
  --market auto|a|hk|us

Data sources:
  A-share: Sina + Tencent quote, Eastmoney F10, Sina daily K
  HK:      Tencent quote + Sina HK quote, Yahoo chart K
  US/ADR:  Yahoo Finance quote/chart + Sina US quote fallback
"""
import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

H = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}
HD = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}
YH = {"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/plain,*/*"}


class FetchError(RuntimeError):
    pass


def retry_call(fn: Callable[[], Any], retries: int = 3, base_delay: float = 0.8, source: str = "") -> Any:
    """Retry HTTP/API calls with exponential backoff."""
    last_exc = None
    for i in range(retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - we want resilient collection, not hard crash
            last_exc = exc
            if i < retries - 1:
                time.sleep(base_delay * (2**i))
    raise FetchError(f"{source or fn.__name__} failed after {retries} retries: {last_exc}")


def to_float(x: Any) -> Optional[float]:
    try:
        if x is None or x == "" or str(x).lower() in {"nan", "none", "null", "-"}:
            return None
        v = float(str(x).replace(",", ""))
        return None if math.isnan(v) or math.isinf(v) else v
    except Exception:
        return None


def market_symbol(code: str, market: str = "auto") -> Tuple[str, str, str, str, str]:
    """Return (secucode, sina_symbol, eastmoney_secid, market_label, yahoo_symbol)."""
    raw = str(code).strip().upper()
    c = raw.replace(".SH", "").replace(".SZ", "").replace(".HK", "").replace(".US", "")
    if market == "auto":
        if re.fullmatch(r"\d{6}", c):
            market = "a"
        elif re.fullmatch(r"\d{1,5}", c) or raw.endswith(".HK"):
            market = "hk"
        else:
            market = "us"
    if market == "a":
        c = c.zfill(6) if c.isdigit() else c
        exch = "SH" if c.startswith(("6", "5", "9")) else "SZ"
        sina = ("sh" if exch == "SH" else "sz") + c
        secid = ("1." if exch == "SH" else "0.") + c
        return f"{c}.{exch}", sina, secid, f"A股 / {'沪市' if exch == 'SH' else '深市'}", f"{c}.{exch}"
    if market == "hk":
        c5 = c.zfill(5) if c.isdigit() else c
        # Tencent/Sina use 5-digit HK codes (hk00700); Yahoo normally uses 4-digit codes (0700.HK).
        cy = c.lstrip("0").zfill(4) if c.isdigit() else c
        return f"{c5}.HK", "hk" + c5, "", "港股 / HKEX", f"{cy}.HK"
    return f"{c}.US", "gb_" + c.lower().replace("-", "$"), "", "美股 / 中概股", c.replace("$", "-")


def get_text(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 12) -> str:
    r = requests.get(url, params=params, headers=headers or H, timeout=timeout)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() in {"iso-8859-1", "ascii"}:
        # Sina/Tencent quote endpoints return GBK frequently.
        r.encoding = "gbk" if ("sinajs" in url or "qt.gtimg.cn" in url) else "utf-8"
    return r.text


def sina_a_quote(symbol: str) -> Dict[str, Any]:
    txt = retry_call(lambda: get_text("https://hq.sinajs.cn/list=" + symbol, headers=H), source="sina_a_quote")
    m = re.search(r'="([^"]*)"', txt)
    if not m:
        return {}
    f = m.group(1).split(",")
    if len(f) < 32 or not f[0]:
        return {}
    price = to_float(f[3])
    prev = to_float(f[2])
    return {
        "source": "新浪A股",
        "name": f[0],
        "open": to_float(f[1]),
        "prev": prev,
        "price": price,
        "high": to_float(f[4]),
        "low": to_float(f[5]),
        "volume": to_float(f[8]),
        "amount": to_float(f[9]),
        "date": f[30] if len(f) > 30 else "",
        "time": f[31] if len(f) > 31 else "",
        "pct": round((price - prev) / prev * 100, 4) if price is not None and prev else None,
    }


def sina_hk_quote(symbol: str) -> Dict[str, Any]:
    txt = retry_call(lambda: get_text("https://hq.sinajs.cn/list=" + symbol, headers=H), source="sina_hk_quote")
    m = re.search(r'="([^"]*)"', txt)
    if not m:
        return {}
    f = m.group(1).split(",")
    if len(f) < 8:
        return {}
    # Common Sina HK format: en_name,zh_name,open,prev_close,high,low,price,...
    price = to_float(f[6]) if len(f) > 6 else None
    prev = to_float(f[3]) if len(f) > 3 else None
    return {
        "source": "新浪港股",
        "name": f[1] or f[0],
        "open": to_float(f[2]),
        "prev": prev,
        "price": price,
        "high": to_float(f[4]),
        "low": to_float(f[5]),
        "volume": to_float(f[12]) if len(f) > 12 else None,
        "amount": to_float(f[11]) if len(f) > 11 else None,
        "date": f[17] if len(f) > 17 else "",
        "time": f[18] if len(f) > 18 else "",
        "pct": round((price - prev) / prev * 100, 4) if price is not None and prev else None,
    }


def sina_us_quote(symbol: str) -> Dict[str, Any]:
    txt = retry_call(lambda: get_text("https://hq.sinajs.cn/list=" + symbol, headers=H), source="sina_us_quote")
    m = re.search(r'="([^"]*)"', txt)
    if not m:
        return {}
    f = m.group(1).split(",")
    if len(f) < 2 or not f[0]:
        return {}
    # Sina US fields vary; use defensive extraction. Often name,price,change,pct,date,time,...
    price = next((to_float(x) for x in f[1:5] if to_float(x) is not None), None)
    pct_val = None
    for x in f[2:8]:
        if "%" in x:
            pct_val = to_float(x.replace("%", ""))
            break
    return {"source": "新浪美股", "name": f[0], "price": price, "pct": pct_val}


def tencent_quote(symbol: str) -> Dict[str, Any]:
    txt = retry_call(lambda: get_text("https://qt.gtimg.cn/q=" + symbol, headers={"User-Agent": "Mozilla/5.0"}), source="tencent_quote")
    m = re.search(r'="(.*)"', txt)
    if not m:
        return {}
    f = m.group(1).split("~")
    def fl(i: int) -> Optional[float]:
        return to_float(f[i]) if len(f) > i else None
    return {
        "source": "腾讯行情",
        "name": f[1] if len(f) > 1 else "",
        "code": f[2] if len(f) > 2 else "",
        "price": fl(3),
        "pct": fl(32),
        "high": fl(33),
        "low": fl(34),
        "turn": fl(38),
        "pe": fl(39),
        "circ_mktcap_yi": fl(44),
        "mktcap_yi": fl(45),
        "amount": fl(37),
    }


def yahoo_quote(yahoo_symbol: str) -> Dict[str, Any]:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": yahoo_symbol}
    j = retry_call(lambda: requests.get(url, params=params, headers=YH, timeout=12).json(), source="yahoo_quote")
    rows = ((j.get("quoteResponse") or {}).get("result") or []) if isinstance(j, dict) else []
    if not rows:
        return {}
    x = rows[0]
    return {
        "source": "Yahoo Finance",
        "name": x.get("shortName") or x.get("longName") or x.get("symbol"),
        "code": x.get("symbol"),
        "price": to_float(x.get("regularMarketPrice")),
        "pct": to_float(x.get("regularMarketChangePercent")),
        "open": to_float(x.get("regularMarketOpen")),
        "prev": to_float(x.get("regularMarketPreviousClose")),
        "high": to_float(x.get("regularMarketDayHigh")),
        "low": to_float(x.get("regularMarketDayLow")),
        "volume": to_float(x.get("regularMarketVolume")),
        "mktcap_yi": round(to_float(x.get("marketCap")) / 1e8, 2) if to_float(x.get("marketCap")) else None,
        "pe": to_float(x.get("trailingPE")),
        "currency": x.get("currency"),
    }


def dc(report: str, secucode: str, size: int = 8) -> List[Dict[str, Any]]:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": report,
        "columns": "ALL",
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": "1",
        "pageSize": str(size),
        "sortTypes": "-1",
        "sortColumns": "REPORT_DATE",
        "source": "WEB",
        "client": "WEB",
    }
    j = retry_call(lambda: requests.get(url, params=params, headers=HD, timeout=18).json(), source=f"eastmoney_{report}")
    return (j.get("result") or {}).get("data") or []


def add_ma(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [r for r in rows if all(r.get(k) is not None for k in ["open", "high", "low", "close"])]
    for i, row in enumerate(rows):
        for ma in [5, 10, 20, 30, 60, 120]:
            if i + 1 >= ma:
                row[f"ma{ma}"] = round(sum(float(r["close"]) for r in rows[i + 1 - ma : i + 1]) / ma, 3)
    return rows


def sina_a_kline(symbol: str, n: int = 120) -> List[Dict[str, Any]]:
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(n)}
    rows = retry_call(lambda: requests.get(url, params=params, headers=H, timeout=18).json(), source="sina_a_kline")
    out = []
    for x in rows or []:
        out.append({"date": x.get("day"), "open": to_float(x.get("open")), "high": to_float(x.get("high")), "low": to_float(x.get("low")), "close": to_float(x.get("close")), "volume": to_float(x.get("volume"))})
    return add_ma(out[-n:])


def yahoo_kline(symbol: str, n: int = 120) -> List[Dict[str, Any]]:
    rng = "6mo" if n <= 140 else "1y"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": rng, "interval": "1d", "events": "history"}
    j = retry_call(lambda: requests.get(url, params=params, headers=YH, timeout=18).json(), source="yahoo_kline")
    result = ((j.get("chart") or {}).get("result") or [{}])[0]
    ts = result.get("timestamp") or []
    q = (((result.get("indicators") or {}).get("quote") or [{}])[0])
    out = []
    for i, t in enumerate(ts):
        row = {"date": time.strftime("%Y-%m-%d", time.localtime(t))}
        for k in ["open", "high", "low", "close", "volume"]:
            vals = q.get(k) or []
            row[k] = to_float(vals[i]) if i < len(vals) else None
        if row.get("close") is not None:
            out.append(row)
    return add_ma(out[-n:])


def yi(x: Any) -> Optional[float]:
    v = to_float(x)
    return None if v is None else round(v / 1e8, 2)


def validate_quotes(quotes: Dict[str, Dict[str, Any]]) -> List[str]:
    warnings = []
    priced = [(k, to_float(v.get("price"))) for k, v in quotes.items() if isinstance(v, dict) and to_float(v.get("price"))]
    for i in range(len(priced)):
        for j in range(i + 1, len(priced)):
            a_name, a_price = priced[i]
            b_name, b_price = priced[j]
            base = max(abs(a_price or 0), abs(b_price or 0), 1)
            diff = abs((a_price or 0) - (b_price or 0)) / base * 100
            if diff > 2:
                warnings.append(f"双源价格差异超过2%：{a_name}={a_price}，{b_name}={b_price}，差异约{diff:.2f}%")
    if not priced:
        warnings.append("未获取到有效实时价格，请人工核验行情源。")
    return warnings


def validate_kline(rows: List[Dict[str, Any]]) -> List[str]:
    warnings = []
    for r in rows[-120:]:
        o, c = to_float(r.get("open")), to_float(r.get("close"))
        if o and c:
            pct = (c - o) / o * 100
            if abs(pct) > 10:
                r["abnormal"] = True
                warnings.append(f"异常K线：{r.get('date')} 单日开收涨跌 {pct:.2f}%（超过10%），需核验复权/停牌/除权因素。")
    return warnings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--kline-days", type=int, default=120)
    ap.add_argument("--market", choices=["auto", "a", "hk", "us"], default="auto", help="auto/a/hk/us; default auto")
    args = ap.parse_args()

    secucode, symbol, secid, market_label, yahoo_symbol = market_symbol(args.code, args.market)
    market_key = "a" if "A股" in market_label else ("hk" if "港股" in market_label else "us")
    warnings: List[str] = []
    errors: Dict[str, str] = {}

    def safe(name: str, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            errors[name] = str(exc)
            warnings.append(f"{name} 获取失败：{exc}")
            return default

    quote_sina: Dict[str, Any] = {}
    quote_tencent: Dict[str, Any] = {}
    quote_yahoo: Dict[str, Any] = {}
    finance: List[Dict[str, Any]] = []
    balance: List[Dict[str, Any]] = []
    cashflow: List[Dict[str, Any]] = []
    mainop: List[Dict[str, Any]] = []

    if market_key == "a":
        quote_sina = safe("新浪A股行情", lambda: sina_a_quote(symbol), {})
        quote_tencent = safe("腾讯A股行情", lambda: tencent_quote(symbol), {})
        finance = safe("东方财富财务", lambda: dc("RPT_F10_FINANCE_MAINFINADATA", secucode, 8), [])
        balance = safe("东方财富资产负债表", lambda: dc("RPT_DMSK_FN_BALANCE", secucode, 5), [])
        cashflow = safe("东方财富现金流量表", lambda: dc("RPT_DMSK_FN_CASHFLOW", secucode, 5), [])
        mainop = safe("东方财富主营构成", lambda: dc("RPT_F10_FN_MAINOP", secucode, 80), [])
        kline = safe("新浪日K", lambda: sina_a_kline(symbol, args.kline_days), [])
        source_label = "新浪+腾讯；东方财富F10；新浪日K"
    elif market_key == "hk":
        quote_sina = safe("新浪港股行情", lambda: sina_hk_quote(symbol), {})
        quote_tencent = safe("腾讯港股行情", lambda: tencent_quote(symbol), {})
        quote_yahoo = safe("Yahoo港股行情", lambda: yahoo_quote(yahoo_symbol), {})
        kline = safe("Yahoo港股日K", lambda: yahoo_kline(yahoo_symbol, args.kline_days), [])
        source_label = "腾讯行情+新浪港股行情；Yahoo日K"
    else:
        quote_yahoo = safe("Yahoo美股行情", lambda: yahoo_quote(yahoo_symbol), {})
        quote_sina = safe("新浪美股行情", lambda: sina_us_quote(symbol), {})
        kline = safe("Yahoo美股日K", lambda: yahoo_kline(yahoo_symbol, args.kline_days), [])
        source_label = "Yahoo Finance；新浪美股行情"

    warnings.extend(validate_quotes({"sina": quote_sina, "tencent": quote_tencent, "yahoo": quote_yahoo}))
    warnings.extend(validate_kline(kline))
    if not kline:
        warnings.append("未获取到有效K线数据，请切换数据源或人工核验。")

    data_sources = [
        {"name": "行情", "source": source_label, "level": "B", "status": "已尽量双源校验；若 warnings 非空请人工复核"},
        {"name": "财报", "source": "东方财富F10/DataCenter（A股）；港股/中概需补公告/年报或Yahoo财务", "level": "A/B", "status": "重要结论建议看公告原文"},
        {"name": "K线", "source": "新浪日K / Yahoo Chart", "level": "B", "status": "用于技术参考；异常K线已标记"},
    ]
    out = {
        "secucode": secucode,
        "symbol": symbol,
        "secid": secid,
        "yahoo_symbol": yahoo_symbol,
        "market": market_label,
        "market_key": market_key,
        "quote_sina": quote_sina,
        "quote_tencent": quote_tencent,
        "quote_yahoo": quote_yahoo,
        "finance": finance,
        "balance": balance,
        "cashflow": cashflow,
        "mainop": mainop,
        "kline": kline,
        "warnings": warnings,
        "errors": errors,
        "data_sources": data_sources,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out)


if __name__ == "__main__":
    main()
