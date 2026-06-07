from __future__ import annotations

import argparse
import html
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPLAY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_ROOT = PROJECT_ROOT / "01_chanlun_sandbox"
if str(SANDBOX_ROOT) not in sys.path:
    sys.path.insert(0, str(SANDBOX_ROOT))

from chanlun_sandbox_app import analyze_payload
from chanlun_v10_20_core import (
    MOMENTUM_THRESHOLD,
    QUANTUM_BUFFER,
    analyze_frame_original,
    macd_momentum,
)


DATA_DIR = Path(r"D:\OneDrive\Stock\details")
DEFAULT_INDEX = "sh000001"
DEFAULT_SYMBOLS = ["sz002463", "sh603078", "sh600522"]
DEFAULT_OUT_DIR = REPLAY_ROOT / "plans"
DEFAULT_CONFIG = REPLAY_ROOT / "plans" / "watchlist_config.json"
MOMENTUM_AREA_FLOOR = 0.0001001

THEME_GROUPS = [
    {
        "official_industries": ["机器人", "机械基础件", "电机制造", "仪器仪表", "系统设备", "工业控制设备", "机床制造", "其他通用设备", "其他专用设备"],
        "market_theme": "机器人 / 具身智能 / 自动化设备",
        "confidence": "高",
        "reading": "按高端制造和自动化分支观察；若只有首日普涨，新增买点仍要等核心回踩承接。",
    },
    {
        "official_industries": ["光纤光缆", "网络接配及塔设", "其他通信设备", "通信终端及配件", "通信工程及服务"],
        "market_theme": "光通信 / CPO / 6G / AI硬件链",
        "confidence": "中高",
        "reading": "仍在科技主线池，优先看容量核心和趋势承接，不把分支轮动当成全线主升。",
    },
    {
        "official_industries": ["PCB", "被动元件", "半导体材料", "集成电路设计", "消费电子组件", "半导体设备", "半导体封测", "其他电子"],
        "market_theme": "AI服务器链 / 高端PCB / MLCC / 半导体材料",
        "confidence": "中高",
        "reading": "前期强势链条要重点区分主线延续和高位兑现；放量下跌时按分歧处理。",
    },
    {
        "official_industries": ["玻璃制造", "面板", "光学元件", "LED"],
        "market_theme": "玻璃基板 / 玻璃玻纤 / 显示链",
        "confidence": "中",
        "reading": "偏轮动分支，除非连续出现梯队和容量核心，否则以观察或小仓试错为主。",
    },
    {
        "official_industries": ["航天装备", "军工电子", "航空装备", "地面兵装"],
        "market_theme": "军工 / 商业航天 / 低空装备",
        "confidence": "中",
        "reading": "适合做分支强弱比较，只有放量扩散并出现核心承接时才提高优先级。",
    },
]

STOCK_THEME_OVERRIDES = {
    "688322": ["机器人 / 具身智能 / 自动化设备"],
    "奥比中光-W": ["机器人 / 具身智能 / 自动化设备"],
    "奥比中光": ["机器人 / 具身智能 / 自动化设备"],
}


@dataclass(frozen=True)
class LevelProjection:
    period: str
    bars: int
    last_close: float
    last_dif: float
    last_macd: float
    zd: float | None
    zg: float | None
    thresholds: dict[str, float | None]
    scenarios: dict[str, dict[str, Any]]


def normalize_symbol(text: str) -> str:
    s = text.strip().lower()
    if s.startswith(("sh", "sz")):
        return s
    if s.startswith("6"):
        return f"sh{s}"
    return f"sz{s}"


def period_name(period: str) -> str:
    if period == "5m":
        return "5Min"
    if period == "30m":
        return "30Min"
    raise ValueError(f"unsupported period: {period}")


def load_frame(symbol: str, period: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol}_{period_name(period)}_MaxAvailable.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def fmt_time(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def number_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace({"--": np.nan, "nan": np.nan, "None": np.nan, "": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def stock_code(symbol: str) -> str:
    s = normalize_symbol(symbol)
    return s[2:]


def find_full_market_file(report_date: str) -> Path | None:
    date_slug = str(report_date).replace("-", "")
    matches = [
        path
        for path in DATA_DIR.glob(f"*{date_slug}.xlsx")
        if path.is_file() and path.stat().st_size > 100_000
    ]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_size)


def read_full_market_frame(report_date: str) -> tuple[pd.DataFrame | None, Path | None, str | None]:
    path = find_full_market_file(report_date)
    if path is None:
        return None, None, "未找到完整全A文件"
    try:
        raw = pd.read_excel(path)
    except Exception as exc:
        return None, path, f"读取失败：{exc}"
    if raw.shape[1] < 28:
        return None, path, f"字段不足：仅 {raw.shape[1]} 列"
    df = pd.DataFrame(
        {
            "code": raw.iloc[:, 0].astype(str).str.extract(r"(\d+)")[0].str.zfill(6),
            "name": raw.iloc[:, 1].astype(str),
            "industry": raw.iloc[:, 2].astype(str),
            "price": raw.iloc[:, 3],
            "pct": number_series(raw.iloc[:, 4]),
            "boards": raw.iloc[:, 6],
            "streak": number_series(raw.iloc[:, 7]),
            "seal_amount": raw.iloc[:, 8],
            "first_seal": raw.iloc[:, 9],
            "open_boards": number_series(raw.iloc[:, 10]),
            "amount_wan": number_series(raw.iloc[:, 12]),
            "main_net_wan": number_series(raw.iloc[:, 14]),
            "open_pct": number_series(raw.iloc[:, 22]),
            "prev_pct": number_series(raw.iloc[:, 27]),
        }
    )
    return df, path, None


def theme_groups_for_industry(industry: str | None) -> list[dict[str, Any]]:
    if not industry:
        return []
    text = str(industry)
    matches = []
    for group in THEME_GROUPS:
        if text in group["official_industries"]:
            matches.append(group)
    return matches


def theme_group_by_market_theme(market_theme: str) -> dict[str, Any] | None:
    for group in THEME_GROUPS:
        if group["market_theme"] == market_theme:
            return group
    return None


def theme_groups_for_stock(row: pd.Series | dict[str, Any]) -> list[dict[str, Any]]:
    code = str(row.get("code") or "").strip().zfill(6)
    name = str(row.get("name") or "").strip()
    override_themes = STOCK_THEME_OVERRIDES.get(code) or STOCK_THEME_OVERRIDES.get(name)
    if override_themes:
        return [group for theme in override_themes if (group := theme_group_by_market_theme(theme))]
    return theme_groups_for_industry(row.get("industry"))


def fmt_100m(value: float | None, digits: int = 0) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}亿"


def plain_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def plain_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{key: plain_value(value) for key, value in row.items()} for row in frame.to_dict("records")]


def leader_names(subset: pd.DataFrame) -> list[str]:
    by_pct = subset.sort_values(["pct", "amount_wan"], ascending=False)["name"].head(6).tolist()
    active = subset[subset["pct"] >= 5].copy()
    by_amount = active.sort_values(["amount_wan", "pct"], ascending=False)["name"].head(6).tolist()
    names: list[str] = []
    for name in [*by_pct, *by_amount]:
        text = str(name)
        if text not in names:
            names.append(text)
    return names[:10]


def build_market_ecology(report_date: str, focus_symbols: list[str]) -> dict[str, Any]:
    df, path, error = read_full_market_frame(report_date)
    if df is None:
        return {"available": False, "source_file": str(path) if path else None, "error": error}
    valid = df[df["pct"].notna()].copy()
    if valid.empty:
        return {"available": False, "source_file": str(path), "error": "全A文件缺少有效涨幅数据"}

    up = int((valid["pct"] > 0).sum())
    down = int((valid["pct"] < 0).sum())
    flat = int((valid["pct"] == 0).sum())
    daily = {
        "sample": int(len(valid)),
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": up / (up + down) if up + down else None,
        "median_pct": safe_float(valid["pct"].median()),
        "limit_up": int((valid["pct"] >= 9.8).sum()),
        "limit_down": int((valid["pct"] <= -9.8).sum()),
        "gt5": int((valid["pct"] >= 5).sum()),
        "lt5": int((valid["pct"] <= -5).sum()),
        "amount_100m": safe_float(valid["amount_wan"].sum() / 10000),
        "main_net_100m": safe_float(valid["main_net_wan"].sum() / 10000),
        "open_up": int((valid["open_pct"] > 0).sum()),
        "open_down": int((valid["open_pct"] < 0).sum()),
    }

    industries = (
        valid[valid["industry"].notna()]
        .groupby("industry")
        .agg(
            n=("code", "count"),
            avg_pct=("pct", "mean"),
            med_pct=("pct", "median"),
            up_ratio=("pct", lambda x: (x > 0).mean()),
            limit_up=("pct", lambda x: (x >= 9.8).sum()),
            gt5=("pct", lambda x: (x >= 5).sum()),
            amount_100m=("amount_wan", lambda x: x.sum() / 10000),
            main_net_100m=("main_net_wan", lambda x: x.sum() / 10000),
        )
        .reset_index()
    )
    industries = industries[industries["n"] >= 5].copy()
    top_avg = industries.sort_values(["avg_pct", "limit_up", "amount_100m"], ascending=False).head(10)
    top_amount = industries.sort_values("amount_100m", ascending=False).head(10)

    theme_rows = []
    valid["_theme_names"] = valid.apply(
        lambda row: [group["market_theme"] for group in theme_groups_for_stock(row)],
        axis=1,
    )
    for group in THEME_GROUPS:
        subset = valid[valid["_theme_names"].apply(lambda themes: group["market_theme"] in themes)].copy()
        if subset.empty:
            continue
        theme_rows.append(
            {
                "market_theme": group["market_theme"],
                "confidence": group["confidence"],
                "official_industries": group["official_industries"],
                "reading": group["reading"],
                "n": int(len(subset)),
                "avg_pct": safe_float(subset["pct"].mean()),
                "up_ratio": safe_float((subset["pct"] > 0).mean()),
                "limit_up": int((subset["pct"] >= 9.8).sum()),
                "gt5": int((subset["pct"] >= 5).sum()),
                "amount_100m": safe_float(subset["amount_wan"].sum() / 10000),
                "main_net_100m": safe_float(subset["main_net_wan"].sum() / 10000),
                "top_names": leader_names(subset),
            }
        )
    theme_rows.sort(
        key=lambda item: (
            safe_float(item.get("avg_pct")) or -99,
            safe_float(item.get("amount_100m")) or 0,
        ),
        reverse=True,
    )

    focus_codes = {stock_code(symbol) for symbol in focus_symbols}
    stock_rows = []
    for _, row in valid[valid["code"].isin(focus_codes)].iterrows():
        groups = theme_groups_for_stock(row)
        stock_rows.append(
            {
                "code": str(row.get("code")),
                "name": row.get("name"),
                "industry": row.get("industry"),
                "market_themes": [g["market_theme"] for g in groups],
                "confidence": groups[0]["confidence"] if groups else "低",
                "reading": groups[0]["reading"] if groups else "未匹配到固定题材层，按官方行业和个股结构单独处理。",
                "pct": safe_float(row.get("pct")),
                "boards": None if pd.isna(row.get("boards")) else row.get("boards"),
                "streak": safe_float(row.get("streak")),
                "amount_100m": safe_float(row.get("amount_wan") / 10000),
                "main_net_100m": safe_float(row.get("main_net_wan") / 10000),
                "open_pct": safe_float(row.get("open_pct")),
                "prev_pct": safe_float(row.get("prev_pct")),
            }
        )

    return {
        "available": True,
        "source_file": str(path),
        "daily": daily,
        "top_industries_by_avg": plain_records(top_avg),
        "top_industries_by_amount": plain_records(top_amount),
        "theme_mappings": theme_rows,
        "focus_stocks": stock_rows,
        "summary": market_ecology_summary(daily, theme_rows),
    }


def market_ecology_summary(daily: dict[str, Any], theme_rows: list[dict[str, Any]]) -> dict[str, str]:
    up_ratio = safe_float(daily.get("up_ratio"))
    median = safe_float(daily.get("median_pct"))
    main_net = safe_float(daily.get("main_net_100m"))
    if up_ratio is not None and up_ratio >= 0.55 and median is not None and median > 0:
        mood = "宽度修复"
    elif up_ratio is not None and up_ratio <= 0.35:
        mood = "弱势分化"
    else:
        mood = "震荡分化"
    if main_net is not None and main_net < -300:
        mood += "，但主力净额明显流出"
    elif main_net is not None and main_net > 100:
        mood += "，且主力净额回流"
    top_themes = [row["market_theme"] for row in theme_rows[:3]]
    mainline = " / ".join(top_themes) if top_themes else "未识别出强题材层"
    risk = "新增买入只看主线核心回踩承接；高成交题材若主力净额转弱，按分歧兑现处理。"
    return {"short_term_mood": mood, "mainline": mainline, "risk_window": risk}


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:+.{digits}f}%"


def price(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def yes_no(value: Any) -> str:
    return "是" if bool(value) else "否"


def relative_label(value: str | None) -> str:
    return {
        "inverse_resistance_alpha": "抗跌型Alpha",
        "trend_amplifier_beta": "大盘放大型Beta",
        "cycle_misaligned_pulse": "脉冲型，抗跌不稳定",
    }.get(value or "", value or "-")


def momentum_area_text(area: dict[str, Any]) -> str:
    previous = safe_float(area.get("previous"))
    current = safe_float(area.get("current"))
    ratio = safe_float(area.get("ratio"))
    if previous is not None and previous <= MOMENTUM_AREA_FLOOR:
        if current is not None and current <= MOMENTUM_AREA_FLOOR:
            return "前后两段几乎都没有有效绿柱，动能面积不可比；这类位置不能用背驰倍数下结论。"
        return "前一段几乎没有有效绿柱，倍率会被极小分母放大；只看结论：最近回调出现了真实绿柱，不能按底背驰处理。"
    if current is not None and current <= MOMENTUM_AREA_FLOOR:
        return "最近回调几乎没有有效绿柱，说明抛压很轻；但若没有跌破前低，只能看作缩量回踩观察，不能直接判底背驰。"
    if ratio is None:
        return "最近一段下跌动能缺少可比前段，暂不判断背驰。"
    if area.get("bottom_divergence"):
        return f"最近一次新低消耗的MACD面积只有前一段的 {ratio:.2f} 倍，杀跌明显衰竭，符合底背驰。"
    if ratio < MOMENTUM_THRESHOLD:
        return f"最近一段下跌动能缩到前一段的 {ratio:.2f} 倍，但几何条件还不完整，只能算背驰观察。"
    if ratio > 1.2:
        return f"最近一段下跌动能反而放大到前一段的 {ratio:.2f} 倍，不能按底背驰处理。"
    return f"最近一段下跌动能约为前一段的 {ratio:.2f} 倍，衰竭不明显。"


def cross_level_text(state30: dict[str, Any]) -> str:
    dif = safe_float(state30.get("dif"))
    slope = safe_float(state30.get("dif_slope_12"))
    if dif is None or slope is None:
        return "30m动量暂缺数据。"
    direction = "向上修复" if slope > 0 else "继续走弱"
    zone = "仍在零轴下方" if dif < 0 else "已经回到零轴上方"
    return f"30m DIF {zone}，但斜率{direction}，说明大级别正在{'修复' if slope > 0 else '承压'}。"


def relative_text(rel: dict[str, Any] | None) -> str:
    if not rel:
        return "未做横截面相对强弱判断。"
    capture = safe_float(rel.get("downside_capture"))
    corr = safe_float(rel.get("corr"))
    klass = relative_label(rel.get("class"))
    if capture is None:
        return f"横截面归类：{klass}。"
    if capture > 1.2:
        extra = "大盘下跌时它跌得更快，不能当硬Alpha。"
    elif capture < 0.5:
        extra = "大盘下跌时它明显抗跌。"
    else:
        extra = "大盘下跌时它大致跟随。"
    return f"横截面归类：{klass}；下跌捕获约 {capture:.2f}，相关度 {price(corr, 2)}，{extra}"


def execution_text(execution: dict[str, Any]) -> str:
    vwap = safe_float(execution.get("vwap"))
    dev = safe_float(execution.get("vwap_dev_pct"))
    chase = bool(execution.get("induced_chase_risk"))
    broken = execution.get("post10_vwap_broken")
    parts = [f"今日VWAP约 {price(vwap)}，收盘相对VWAP {pct(dev)}。"]
    if dev is not None and dev > 2:
        parts.append("收盘偏离较大，明日追高容易买在日内均价上方。")
    elif dev is not None and dev < -1:
        parts.append("收盘低于VWAP，说明承接还弱。")
    else:
        parts.append("价格和VWAP贴近，适合等方向选择。")
    if chase:
        parts.append("早盘有明显急拉偏离，明日仍要防开盘诱多。")
    if broken is True:
        parts.append("10点后曾跌破VWAP，承接质量一般。")
    elif broken is False:
        parts.append("10点后未有效跌破VWAP，承接相对较好。")
    return "".join(parts)


def projection_text(proj: dict[str, Any]) -> str:
    th = proj.get("thresholds") or {}
    last_close = safe_float(proj.get("last_close"))
    macd_improve = safe_float(th.get("flat_close_for_macd_improve"))
    dif_hold = safe_float(th.get("next_close_for_dif_above_last_bottom"))
    zd = safe_float(proj.get("zd"))
    zg = safe_float(proj.get("zg"))
    period = proj.get("period")
    pieces = []
    if macd_improve is not None and last_close is not None:
        if macd_improve <= last_close:
            pieces.append(f"{period}若守在 {price(macd_improve)} 上方，绿柱大概率不再恶化")
        else:
            pieces.append(f"{period}若反弹并站上 {price(macd_improve)}，绿柱才更容易缩短")
    elif macd_improve is not None:
        pieces.append(f"{period}若守在 {price(macd_improve)} 上方，绿柱大概率不再恶化")
    if dif_hold is not None and last_close is not None:
        if dif_hold < last_close * 0.95:
            pieces.append("DIF守住前低的要求很宽，关键转为看回踩结构位是否守住")
        elif dif_hold <= last_close:
            pieces.append(f"只要不有效跌破 {price(dif_hold)}，DIF仍有机会守住最近底分型强度")
        else:
            pieces.append(f"若上攻到 {price(dif_hold)} 附近，DIF修复会更强")
    if zg is not None and zd is not None:
        if last_close is not None and last_close > zg:
            pieces.append(f"回踩优先看 {price(zg)}，跌回 {price(zd)} 下方则修复失败")
        elif last_close is not None and zd <= last_close <= zg:
            pieces.append(f"站上 {price(zg)} 才转强，跌破 {price(zd)} 转弱")
        else:
            pieces.append(f"先看能否收回 {price(zd)}，否则仍是弱修复")
    return "；".join(pieces) + "。"


def get_row_at(df: pd.DataFrame, ts: Any) -> pd.Series | None:
    row = df.loc[df["time"].eq(pd.Timestamp(ts))]
    if row.empty:
        return None
    return row.iloc[0]


def fractal_pack(fractal: dict[str, Any] | None, df: pd.DataFrame) -> dict[str, Any] | None:
    if not fractal:
        return None
    row = get_row_at(df, fractal["date"])
    return {
        "time": fmt_time(fractal["date"]),
        "type": fractal["type"],
        "value": float(fractal["val"]),
        "dif": safe_float(row["DIF"]) if row is not None else None,
        "macd": safe_float(row["MACD"]) if row is not None else None,
    }


def center_pack(zs: dict[str, Any] | None) -> dict[str, Any] | None:
    if not zs:
        return None
    return {
        "start": fmt_time(zs["start"]),
        "end": fmt_time(zs["end"]),
        "ZD": float(zs["ZD"]),
        "ZG": float(zs["ZG"]),
    }


def day_stats(df: pd.DataFrame, is_index: bool = False) -> dict[str, Any]:
    day = df["time"].dt.date.iloc[-1]
    d = df.loc[df["time"].dt.date.eq(day)].copy()
    out = {
        "date": str(day),
        "open": float(d["open"].iloc[0]),
        "high": float(d["high"].max()),
        "low": float(d["low"].min()),
        "close": float(d["close"].iloc[-1]),
        "last_time": fmt_time(d["time"].iloc[-1]),
    }
    first30 = d.loc[d["time"].dt.time <= pd.Timestamp("10:00").time()]
    post10 = d.loc[d["time"].dt.time > pd.Timestamp("10:00").time()]
    out.update(
        {
            "first30_high": float(first30["high"].max()) if not first30.empty else None,
            "first30_low": float(first30["low"].min()) if not first30.empty else None,
            "first30_close": float(first30["close"].iloc[-1]) if not first30.empty else None,
            "post10_high": float(post10["high"].max()) if not post10.empty else None,
            "post10_low": float(post10["low"].min()) if not post10.empty else None,
        }
    )
    if not is_index and "volume" in d.columns:
        volume_cumsum = d["volume"].replace(0, np.nan).cumsum()
        if "amount" in d.columns and safe_float(d["amount"].sum()) not in (None, 0.0):
            weighted_turnover = d["amount"].cumsum()
            vwap_source = "amount"
        else:
            typical_price = (d["high"] + d["low"] + d["close"]) / 3
            weighted_turnover = (typical_price * d["volume"]).cumsum()
            vwap_source = "volume_typical_price"
        d["vwap"] = weighted_turnover / volume_cumsum
        d["vwap"] = d["vwap"].ffill()
        d["vwap_dev_pct"] = (d["close"] / d["vwap"] - 1) * 100
        first30 = d.loc[d["time"].dt.time <= pd.Timestamp("10:00").time()]
        post10 = d.loc[d["time"].dt.time > pd.Timestamp("10:00").time()]
        out.update(
            {
                "vwap": safe_float(d["vwap"].iloc[-1]),
                "vwap_source": vwap_source,
                "vwap_dev_pct": safe_float(d["vwap_dev_pct"].iloc[-1]),
                "first30_vwap_max_dev_pct": safe_float(first30["vwap_dev_pct"].max()) if not first30.empty else None,
                "first30_vwap_min_dev_pct": safe_float(first30["vwap_dev_pct"].min()) if not first30.empty else None,
                "post10_vwap_broken": bool((post10["close"] < post10["vwap"]).any()) if not post10.empty else None,
            }
        )
    return out


def previous_fractal(fractals: list[dict[str, Any]], ts: Any, kind: str) -> dict[str, Any] | None:
    t = pd.Timestamp(ts)
    return next((f for f in reversed(fractals) if f["type"] == kind and pd.Timestamp(f["date"]) < t), None)


def momentum_leg_area(df: pd.DataFrame, fractals: list[dict[str, Any]], target: dict[str, Any] | None) -> float | None:
    if not target:
        return None
    if target["type"] == "Bottom":
        start = previous_fractal(fractals, target["date"], "Top")
        direction = -1
    else:
        start = previous_fractal(fractals, target["date"], "Bottom")
        direction = 1
    if not start:
        return None
    return macd_momentum(df, start["date"], target["date"], direction)


def build_geometry_and_momentum(df: pd.DataFrame, period: str) -> dict[str, Any]:
    result = analyze_frame_original(df, period)
    data = result["df"].copy()
    fractals = sorted(result.get("fractals", []), key=lambda x: x["date"])
    centers = sorted(result.get("zs", []), key=lambda z: z["end"])
    active_zs = centers[-1] if centers else None

    bottoms = [f for f in fractals if f["type"] == "Bottom"]
    tops = [f for f in fractals if f["type"] == "Top"]
    prev_bottom = bottoms[-2] if len(bottoms) >= 2 else None
    last_bottom = bottoms[-1] if bottoms else None
    prev_top = tops[-2] if len(tops) >= 2 else None
    last_top = tops[-1] if tops else None

    active_fractals = []
    if active_zs:
        start = pd.Timestamp(active_zs["start"])
        end = pd.Timestamp(active_zs["end"])
        active_fractals = [f for f in fractals if start <= pd.Timestamp(f["date"]) <= end]

    prev_down_area = momentum_leg_area(data, fractals, prev_bottom)
    last_down_area = momentum_leg_area(data, fractals, last_bottom)
    prev_up_area = momentum_leg_area(data, fractals, prev_top)
    last_up_area = momentum_leg_area(data, fractals, last_top)

    def ratio(a: float | None, b: float | None) -> float | None:
        if a is None or b is None or a == 0:
            return None
        return b / a

    bottom_divergence = False
    bottom_quantum_trap = False
    if prev_bottom and last_bottom and prev_down_area and last_down_area:
        prev_val = float(prev_bottom["val"])
        last_val = float(last_bottom["val"])
        broke = last_val < prev_val
        near_break = last_val >= prev_val * (1 - QUANTUM_BUFFER)
        bottom_quantum_trap = broke and near_break
        bottom_divergence = broke and not near_break and last_down_area < prev_down_area * MOMENTUM_THRESHOLD

    top_divergence = False
    top_quantum_trap = False
    if prev_top and last_top and prev_up_area and last_up_area:
        prev_val = float(prev_top["val"])
        last_val = float(last_top["val"])
        broke = last_val > prev_val
        near_break = last_val <= prev_val * (1 + QUANTUM_BUFFER)
        top_quantum_trap = broke and near_break
        top_divergence = broke and not near_break and last_up_area < prev_up_area * MOMENTUM_THRESHOLD

    return {
        "center": center_pack(active_zs),
        "active_center_fractal_count": len(active_fractals),
        "nine_bi_lifecycle_warning": len(active_fractals) >= 9,
        "last_bottom": fractal_pack(last_bottom, data),
        "prev_bottom": fractal_pack(prev_bottom, data),
        "last_top": fractal_pack(last_top, data),
        "prev_top": fractal_pack(prev_top, data),
        "down_area": {
            "previous": prev_down_area,
            "current": last_down_area,
            "ratio": ratio(prev_down_area, last_down_area),
            "bottom_divergence": bottom_divergence,
            "quantum_trap": bottom_quantum_trap,
        },
        "up_area": {
            "previous": prev_up_area,
            "current": last_up_area,
            "ratio": ratio(prev_up_area, last_up_area),
            "top_divergence": top_divergence,
            "quantum_trap": top_quantum_trap,
        },
    }


def build_30m_state(symbol: str) -> dict[str, Any]:
    df = load_frame(symbol, "30m")
    result = analyze_frame_original(df, "30m")
    data = result["df"].copy()
    dif = data["DIF"].tail(12).to_numpy()
    slope = float(np.polyfit(np.arange(len(dif)), dif, 1)[0]) if len(dif) > 1 else 0.0
    return {
        "last_time": fmt_time(data["time"].iloc[-1]),
        "close": float(data["close"].iloc[-1]),
        "dif": float(data["DIF"].iloc[-1]),
        "dea": float(data["DEA"].iloc[-1]),
        "macd": float(data["MACD"].iloc[-1]),
        "dif_slope_12": slope,
        "recent_signals": [
            {"time": fmt_time(s["date"]), "label": s["label"], "value": float(s["val"])}
            for s in result.get("signals", [])[-5:]
        ],
    }


def build_execution_state(df: pd.DataFrame, is_index: bool = False) -> dict[str, Any]:
    stats = day_stats(df, is_index=is_index)
    if is_index:
        return {
            "cooling_protocol": "index_vwap_skipped",
            "day": stats,
        }
    max_dev = stats.get("first30_vwap_max_dev_pct")
    min_dev = stats.get("first30_vwap_min_dev_pct")
    induced_chase_risk = max_dev is not None and max_dev >= 1.5
    panic_flush = min_dev is not None and min_dev <= -1.5
    return {
        "cooling_protocol": "09:30-10:00 no blind buy",
        "vwap": stats.get("vwap"),
        "vwap_source": stats.get("vwap_source"),
        "vwap_dev_pct": stats.get("vwap_dev_pct"),
        "first30_vwap_max_dev_pct": max_dev,
        "first30_vwap_min_dev_pct": min_dev,
        "post10_vwap_broken": stats.get("post10_vwap_broken"),
        "induced_chase_risk": induced_chase_risk,
        "panic_flush": panic_flush,
        "day": stats,
    }


def ema_projection_state(df: pd.DataFrame) -> tuple[float, float, float, float, float, float]:
    ema12 = float(df["close"].ewm(span=12, adjust=False).mean().iloc[-1])
    ema26 = float(df["close"].ewm(span=26, adjust=False).mean().iloc[-1])
    dea = float(df["DEA"].iloc[-1])
    return ema12, ema26, dea, 2 / 13, 2 / 27, 2 / 10


def project_macd(df: pd.DataFrame, closes: list[float]) -> list[dict[str, Any]]:
    ema12, ema26, dea, a12, a26, a9 = ema_projection_state(df)
    rows = []
    neg_area = 0.0
    pos_area = 0.0
    for i, close in enumerate(closes, 1):
        ema12 = ema12 + a12 * (close - ema12)
        ema26 = ema26 + a26 * (close - ema26)
        dif = ema12 - ema26
        dea = dea + a9 * (dif - dea)
        macd = 2 * (dif - dea)
        if macd < 0:
            neg_area += abs(macd)
        if macd > 0:
            pos_area += macd
        rows.append(
            {
                "bar": i,
                "close": close,
                "dif": dif,
                "macd": macd,
                "negative_area": neg_area,
                "positive_area": pos_area,
            }
        )
    return rows


def min_close_for_condition(df: pd.DataFrame, fn) -> float | None:
    close = float(df["close"].iloc[-1])
    lo = close * 0.88
    hi = close * 1.12
    step = (hi - lo) / 5000
    current = lo
    while current <= hi:
        if fn(current):
            return current
        current += step
    return None


def build_projection(symbol: str, period: str, bars: int) -> LevelProjection:
    df_raw = load_frame(symbol, period)
    result = analyze_frame_original(df_raw, period)
    df = result["df"].copy()
    geo = build_geometry_and_momentum(df_raw, period)
    center = geo.get("center")
    zd = center.get("ZD") if center else None
    zg = center.get("ZG") if center else None
    last_close = float(df["close"].iloc[-1])
    last_dif = float(df["DIF"].iloc[-1])
    last_macd = float(df["MACD"].iloc[-1])
    day = day_stats(df_raw, is_index=symbol == DEFAULT_INDEX)

    last_bottom = geo.get("last_bottom")
    prev_bottom = geo.get("prev_bottom")
    thresholds: dict[str, float | None] = {
        "flat_close_for_macd_improve": min_close_for_condition(
            df,
            lambda c: project_macd(df, [c] * min(3, bars))[-1]["macd"] > last_macd,
        ),
    }
    if last_bottom and last_bottom.get("dif") is not None:
        target = float(last_bottom["dif"])
        thresholds["next_close_for_dif_above_last_bottom"] = min_close_for_condition(
            df, lambda c: project_macd(df, [c])[0]["dif"] >= target
        )
    if prev_bottom and prev_bottom.get("dif") is not None:
        target = float(prev_bottom["dif"])
        thresholds["next_close_for_dif_above_prev_bottom"] = min_close_for_condition(
            df, lambda c: project_macd(df, [c])[0]["dif"] >= target
        )

    support = zd if zd is not None else day["low"]
    resistance = zg if zg is not None else day["high"]
    if last_close >= resistance:
        hold = [last_close] * bars
        pullback = list(np.linspace(last_close, resistance, bars))
        reclaim = list(np.linspace(last_close, max(last_close, day["high"]), bars))
        fail = list(np.linspace(last_close, support, bars))
    else:
        hold = list(np.linspace(last_close, support, bars))
        pullback = [day["low"] * 0.998, day["low"], (day["low"] + support) / 2, support]
        pullback = (pullback + [support] * bars)[:bars]
        reclaim = list(np.linspace(last_close, resistance, bars))
        fail = list(np.linspace(last_close, day["low"] * 0.97, bars))

    scenarios: dict[str, dict[str, Any]] = {}
    for name, closes in {
        "hold_current": hold,
        "pullback_or_shallow_break": pullback,
        "repair_to_resistance": reclaim,
        "continue_down": fail,
    }.items():
        rows = project_macd(df, [float(c) for c in closes])
        checkpoints = [rows[0], rows[min(len(rows) - 1, max(0, bars // 2 - 1))], rows[-1]]
        scenarios[name] = {
            "checkpoints": checkpoints,
            "final": rows[-1],
        }

    return LevelProjection(
        period=period,
        bars=bars,
        last_close=last_close,
        last_dif=last_dif,
        last_macd=last_macd,
        zd=zd,
        zg=zg,
        thresholds=thresholds,
        scenarios=scenarios,
    )


def build_relative_strength(symbol: str, index_df: pd.DataFrame) -> dict[str, Any] | None:
    if symbol == DEFAULT_INDEX:
        return None
    df = load_frame(symbol, "5m")
    last_days = sorted(index_df["time"].dt.date.unique())[-20:]
    idx = index_df.loc[index_df["time"].dt.date.isin(last_days), ["time", "close"]]
    stk = df.loc[df["time"].dt.date.isin(last_days), ["time", "close"]]
    merged = idx.merge(stk, on="time", suffixes=("_idx", "_stock"))
    merged["idx_ret"] = merged["close_idx"].pct_change() * 100
    merged["stock_ret"] = merged["close_stock"].pct_change() * 100
    merged = merged.dropna()
    if merged.empty:
        return None
    risk = merged.loc[(merged["idx_ret"] <= merged["idx_ret"].quantile(0.15)) & (merged["idx_ret"] < 0)]
    if risk.empty:
        return None
    capture = float(risk["stock_ret"].sum() / risk["idx_ret"].sum()) if risk["idx_ret"].sum() != 0 else None
    corr = float(merged["idx_ret"].corr(merged["stock_ret"]))
    avg_idx = float(risk["idx_ret"].mean())
    avg_stock = float(risk["stock_ret"].mean())
    if capture is not None and capture < 0.35 and avg_stock > avg_idx * 0.45:
        klass = "inverse_resistance_alpha"
    elif capture is not None and corr > 0.55 and capture > 0.85:
        klass = "trend_amplifier_beta"
    else:
        klass = "cycle_misaligned_pulse"
    return {
        "class": klass,
        "downside_capture": capture,
        "corr": corr,
        "risk_windows": int(len(risk)),
        "avg_index_drop_pct": avg_idx,
        "avg_stock_move_pct": avg_stock,
    }


def gate_state(current: dict[str, Any]) -> str:
    state = current.get("state")
    if state == "above_active_bi_zs":
        return "red"
    if state == "inside_active_bi_zs":
        return "yellow"
    if state == "below_active_bi_zs":
        return "blue"
    return "unknown"


def center_position(close: float | None, center: dict[str, Any] | None) -> str:
    if close is None or not center:
        return "结构不明"
    zd = safe_float(center.get("ZD"))
    zg = safe_float(center.get("ZG"))
    if zd is None or zg is None:
        return "结构不明"
    if close > zg:
        return "中枢上方"
    if close < zd:
        return "中枢下方"
    return "中枢内部"


def gate_plain_text(gate: str, current: dict[str, Any], center: dict[str, Any] | None) -> str:
    close = safe_float(current.get("price"))
    pos = center_position(close, center)
    if gate == "red":
        return f"偏红：指数收在5m{pos}，可以观察趋势延续，但仍等回踩确认。"
    if gate == "yellow":
        return f"黄色：指数收在5m{pos}，市场还在震荡区，个股只做承接验证。"
    if gate == "blue":
        return f"偏蓝：指数收在5m{pos}，新增买点降级，持仓按各自利润垫和破位线处理。"
    return f"观察：指数位置为5m{pos}，总闸暂不清晰。"


def build_symbol_report(symbol: str, index_df: pd.DataFrame) -> dict[str, Any]:
    df5 = load_frame(symbol, "5m")
    payload = analyze_payload(symbol, "5m", "", "balanced")
    geometry_5m = build_geometry_and_momentum(df5, "5m")
    projection_5m = build_projection(symbol, "5m", 6)
    projection_30m = build_projection(symbol, "30m", 2)
    return {
        "symbol": symbol,
        "day": day_stats(df5, is_index=symbol == DEFAULT_INDEX),
        "current": payload["current"],
        "summary": payload["summary"],
        "geometry_5m": geometry_5m,
        "state_30m": build_30m_state(symbol),
        "projection_5m": projection_5m.__dict__,
        "projection_30m": projection_30m.__dict__,
        "execution": build_execution_state(df5, is_index=symbol == DEFAULT_INDEX),
        "relative_strength": build_relative_strength(symbol, index_df),
        "recent_signals": [
            {
                "time": s.get("time"),
                "label": s.get("label"),
                "price": s.get("price"),
                "level": s.get("level"),
                "status": s.get("status"),
            }
            for layer in payload.get("layers", [])
            for s in layer.get("signals", [])
        ][-8:],
    }


def trade_type(position: dict[str, Any] | None) -> str:
    role = (position or {}).get("role") or "趋势标的"
    if "超短" in role or "打野" in role:
        return "打野"
    if "防守" in role:
        return "防守"
    if "短线" in role:
        return "短线"
    return "趋势"


def classify_symbol(report: dict[str, Any], index_gate: str, position: dict[str, Any] | None = None) -> tuple[str, str]:
    cur = report["current"]
    close = safe_float(cur.get("price"))
    center = report["geometry_5m"].get("center")
    rel = report.get("relative_strength") or {}
    exec_state = report.get("execution") or {}
    state30 = report.get("state_30m") or {}
    pos_label = center_position(close, center)
    slope = safe_float(state30.get("dif_slope_12")) or 0.0
    profit_pct = safe_float((position or {}).get("profit_pct"))
    has_profit_cushion = profit_pct is not None and profit_pct >= 10
    day = report.get("day") or {}
    day_high = safe_float(day.get("high"))
    vwap_dev = safe_float(exec_state.get("vwap_dev_pct"))
    strong_close = close is not None and day_high is not None and close >= day_high * 0.999
    strong_extension = pos_label == "中枢上方" and strong_close and (vwap_dev is not None and vwap_dev >= 3.0)

    if index_gate == "blue":
        if strong_extension and has_profit_cushion:
            return "strong_hold_no_add", "大盘偏蓝限制新增仓，但该票放量冲到日高并站在5m中枢上方，持仓享受强势，不追高加仓。"
        if pos_label == "中枢下方":
            if has_profit_cushion:
                return "hold_reduce_activity", "大盘偏蓝且个股跌到5m中枢下方，底仓可看30m，活动仓优先降风险。"
            return "reduce_risk", "大盘偏蓝且个股跌到5m中枢下方，利润垫不厚，优先保护现金。"
        if slope > 0 and has_profit_cushion:
            return "hold_verify", "大盘偏蓝只限制新增买入；该票30m仍修复且有利润垫，按持仓观察处理。"
        return "observe_no_add", "大盘偏蓝，新增买点降级为观察，等指数总闸修复后再谈加仓。"

    if center and close is not None and close > center["ZG"] and slope > 0:
        if exec_state.get("vwap_dev_pct") is not None and exec_state["vwap_dev_pct"] > 2.0:
            return "strong_but_wait_pullback", "结构强，但收盘偏离VWAP过大，明日等回踩"
        return "offense_watch", "5m离开中枢且30m动量向上"
    if center and close is not None and center["ZD"] <= close <= center["ZG"]:
        return "range_watch", "位于5m中枢内，等待离开方向"
    if rel.get("class") == "inverse_resistance_alpha":
        return "alpha_watch", "风险窗口抗跌，优先观察承接"
    return "repair_or_defense", "未形成清晰进攻结构，按修复或防守处理"


def action_label(action: str) -> str:
    return {
        "offense_watch": "进攻观察",
        "strong_but_wait_pullback": "强势但等回踩",
        "range_watch": "中枢震荡观察",
        "repair_or_defense": "修复/防守",
        "alpha_watch": "抗跌Alpha观察",
        "defense": "防守",
        "hold_verify": "持有观察",
        "hold_reduce_activity": "底仓观察/活动仓降风险",
        "observe_no_add": "只观察不加仓",
        "reduce_risk": "减仓防守",
        "strong_hold_no_add": "强势持仓/不追加",
    }.get(action, action)


def action_rank(action: str) -> int:
    return {
        "offense_watch": 1,
        "strong_but_wait_pullback": 2,
        "alpha_watch": 3,
        "hold_verify": 3,
        "strong_hold_no_add": 3,
        "range_watch": 4,
        "observe_no_add": 5,
        "repair_or_defense": 5,
        "hold_reduce_activity": 6,
        "defense": 6,
        "reduce_risk": 7,
    }.get(action, 9)


def render_projection_line(proj: dict[str, Any]) -> str:
    return projection_text(proj)


def concise_action_card(
    report: dict[str, Any],
    index_gate: str = "unknown",
    is_index: bool = False,
    position: dict[str, Any] | None = None,
) -> list[str]:
    center = report["geometry_5m"].get("center")
    state30 = report.get("state_30m") or {}
    proj5 = report.get("projection_5m") or {}
    th5 = proj5.get("thresholds") or {}
    day = report.get("day") or {}
    execution = report.get("execution") or {}
    close = safe_float(day.get("close"))
    zd = safe_float(center.get("ZD")) if center else None
    zg = safe_float(center.get("ZG")) if center else None
    macd_improve = safe_float(th5.get("flat_close_for_macd_improve"))
    dif_hold = safe_float(th5.get("next_close_for_dif_above_last_bottom"))
    lines: list[str] = []

    if is_index:
        pos = center_position(close, center)
        slope_text = "向上修复" if state30.get("dif_slope_12", 0) > 0 else "继续走弱"
        action_paths = index_action_paths(report)
        red_gate = action_paths["red"]["title"].replace("红色路径：", "")
        yellow_gate = action_paths["yellow"]["title"].replace("黄色路径：", "")
        blue_gate = action_paths["blue"]["title"].replace("蓝色路径：", "")
        lines.append(f"{report['symbol']}：{gate_plain_text(index_gate, report.get('current') or {}, center)}")
        lines.append(
            f"今日结构：收盘 {price(close)}，位置在5m{pos}，30m DIF{slope_text}。"
        )
        lines.append(
            f"明日总闸：{red_gate}，风险降级；{yellow_gate}，只做验证；{blue_gate}，全场转防守。"
        )
        lines.append(
            f"动量提示：5m守住 {price(macd_improve)} 附近，绿柱倾向缩短；守住/站回 {price(dif_hold)} 附近，DIF修复更稳。"
        )
        return lines

    action, reason = classify_symbol(report, index_gate, position)
    typ = trade_type(position)
    pos = center_position(close, center)
    slope_text = "向上" if state30.get("dif_slope_12", 0) > 0 else "走弱"
    vwap_dev = safe_float(execution.get("vwap_dev_pct"))
    vwap = safe_float(execution.get("vwap"))
    profit_pct = safe_float((position or {}).get("profit_pct"))
    name = (position or {}).get("name") or report.get("symbol")
    cushion = "利润垫厚" if profit_pct is not None and profit_pct >= 10 else "利润垫薄" if profit_pct is not None else "利润垫未配置"
    vwap_text = f"VWAP {price(vwap)}，收盘偏离 {pct(vwap_dev)}" if vwap_dev is not None else "VWAP未计算"
    lines.append(f"{report['symbol']} {name}：交易类型：{typ}；执行结论：{action_label(action)}。")
    lines.append(f"今日一句话：收在5m{pos}，30m DIF{slope_text}，{vwap_text}，{cushion}。")
    if zg is not None and close is not None and close > zg:
        lines.append(
            f"买点条件：不追高；回踩 {price(zg)} 或VWAP不破，再看5m二买/三买延续。"
        )
    elif zd is not None and zg is not None and close is not None and zd <= close <= zg:
        lines.append(
            f"买点条件：先看方向选择；站上 {price(zg)} 才转强，回踩不破VWAP再考虑活动仓。"
        )
    else:
        lines.append(
            f"买点条件：先收回 {price(zd)}；若仍在中枢下方，所有买点只观察。"
        )
    lines.append(f"卖点/减仓条件：跌破 {price(zd)} 后不能快速收回，或10点后持续压在VWAP下方。")
    lines.append(f"失效条件：大盘跌破总闸下沿，同时个股5m跌破 {price(zd)}，活动仓先让路。")
    if dif_hold is not None and close is not None:
        if dif_hold < close * 0.95:
            lines.append(
                "动量提示：DIF守最近底的条件已经很宽，明日重点不是猜背离，而是看结构位/VWAP能不能托住。"
            )
        else:
            lines.append(
                f"动量提示：若价格守住/站回 {price(dif_hold)} 附近，DIF有望守住最近底分型强度；低于该阈值更像弱修复。"
            )
    elif dif_hold is not None:
        lines.append(
            f"动量提示：若价格守住/站回 {price(dif_hold)} 附近，DIF有望守住最近底分型强度；低于该阈值更像弱修复。"
        )
    return lines


def theme_summary_line(ecology: dict[str, Any]) -> str:
    if not ecology.get("available"):
        return f"题材生态暂缺全A数据：{ecology.get('error') or '未知原因'}。"
    summary = ecology.get("summary") or {}
    daily = ecology.get("daily") or {}
    up_ratio = safe_float(daily.get("up_ratio"))
    up_ratio_pct = up_ratio * 100 if up_ratio is not None else None
    return (
        f"{summary.get('short_term_mood') or '市场分化'}；"
        f"全A上涨占比 {pct(up_ratio_pct, 1)}，中位涨幅 {pct(safe_float(daily.get('median_pct')))}；"
        f"题材主线层：{summary.get('mainline') or '未识别'}。"
    )


def render_industry_rows(rows: list[dict[str, Any]], limit: int = 6) -> list[str]:
    lines = []
    for row in rows[:limit]:
        lines.append(
            f"{row.get('industry')}：均涨 {pct(safe_float(row.get('avg_pct')))}，"
            f"上涨占比 {pct((safe_float(row.get('up_ratio')) or 0) * 100, 0)}，"
            f"涨停 {int(row.get('limit_up') or 0)}，成交 {fmt_100m(safe_float(row.get('amount_100m')), 1)}，"
            f"主力净额 {fmt_100m(safe_float(row.get('main_net_100m')), 1)}"
        )
    return lines


def render_market_ecology(lines: list[str], ecology: dict[str, Any], market_context: dict[str, Any]) -> None:
    lines.append("## 0.1 市场生态")
    lines.append("")
    if any(market_context.values()):
        lines.append("```text")
        lines.append(f"短线情绪：{market_context.get('short_term_mood') or '未填写'}")
        lines.append(f"主线方向：{market_context.get('mainline') or '未填写'}")
        lines.append(f"机构趋势：{market_context.get('institutional_direction') or '未填写'}")
        lines.append(f"风险窗口：{market_context.get('risk_window') or '未填写'}")
        lines.append("```")
        lines.append("")

    if not ecology.get("available"):
        lines.append(f"全市场情绪层暂不可用：{ecology.get('error') or '未找到全A数据'}。")
        if ecology.get("source_file"):
            lines.append(f"尝试文件：{ecology['source_file']}")
        lines.append("")
        return

    daily = ecology.get("daily") or {}
    lines.append("### 0.1.1 全市场情绪层")
    lines.append("")
    lines.append(f"基于 `{ecology.get('source_file')}`：")
    lines.append("")
    lines.append("```text")
    lines.append(f"有效样本：{daily.get('sample')}")
    lines.append(f"上涨 / 下跌 / 平盘：{daily.get('up')} / {daily.get('down')} / {daily.get('flat')}")
    lines.append(f"上涨占比：{pct((safe_float(daily.get('up_ratio')) or 0) * 100, 1)}")
    lines.append(f"中位涨幅：{pct(safe_float(daily.get('median_pct')))}")
    lines.append(f"涨停 / 跌停：{daily.get('limit_up')} / {daily.get('limit_down')}")
    lines.append(f"涨幅 >= 5% / 跌幅 <= -5%：{daily.get('gt5')} / {daily.get('lt5')}")
    lines.append(f"全市场成交额：约 {fmt_100m(safe_float(daily.get('amount_100m')), 0)}")
    lines.append(f"主力净额：约 {fmt_100m(safe_float(daily.get('main_net_100m')), 0)}")
    lines.append("```")
    lines.append("")
    lines.append(f"结论：{theme_summary_line(ecology)}")
    lines.append("")

    lines.append("### 0.1.2 官方行业 -> 市场题材映射")
    lines.append("")
    lines.append("```text")
    for row in ecology.get("theme_mappings", [])[:6]:
        lines.append(f"官方行业：{' / '.join(row.get('official_industries') or [])}")
        lines.append(f"市场题材：{row.get('market_theme')}")
        lines.append(f"匹配置信度：{row.get('confidence')}")
        lines.append(
            f"本地证据：样本 {row.get('n')}，均涨 {pct(safe_float(row.get('avg_pct')))}，"
            f"涨停 {row.get('limit_up')}，成交 {fmt_100m(safe_float(row.get('amount_100m')), 1)}，"
            f"主力净额 {fmt_100m(safe_float(row.get('main_net_100m')), 1)}"
        )
        tops = "、".join(str(x) for x in (row.get("top_names") or [])[:5])
        if tops:
            lines.append(f"强势样本：{tops}")
        lines.append(f"复盘结论：{row.get('reading')}")
        lines.append("")
    lines.append("```")
    lines.append("")

    industry_rows = render_industry_rows(ecology.get("top_industries_by_avg") or [])
    if industry_rows:
        lines.append("### 0.1.3 官方行业强弱")
        lines.append("")
        lines.append("```text")
        lines.extend(industry_rows)
        lines.append("```")
        lines.append("")

    focus_rows = ecology.get("focus_stocks") or []
    if focus_rows:
        lines.append("### 0.1.4 持仓题材归因")
        lines.append("")
        lines.append("```text")
        for row in focus_rows:
            symbol = normalize_symbol(str(row.get("code")))
            themes = " / ".join(row.get("market_themes") or ["未匹配固定题材"])
            lines.append(f"{symbol} {row.get('name')}")
            lines.append(f"官方行业：{row.get('industry')}")
            lines.append(f"市场题材：{themes}")
            lines.append(f"匹配置信度：{row.get('confidence')}")
            lines.append(
                f"今日表现：{pct(safe_float(row.get('pct')))}，成交约 {fmt_100m(safe_float(row.get('amount_100m')), 1)}，"
                f"主力净额约 {fmt_100m(safe_float(row.get('main_net_100m')), 1)}"
            )
            if row.get("boards") not in (None, "nan", "--"):
                lines.append(f"连板/强势字段：{row.get('boards')}")
            lines.append(f"复盘含义：{row.get('reading')}")
            lines.append("")
        lines.append("```")
        lines.append("")
    lines.append("资料口径：本地全A数据负责回答“谁真的涨、谁放量、谁涨停、谁流入/流出”；题材映射只用于解释市场可能按什么故事交易，不替代本地量价证据。")
    lines.append("")


def render_report(data: dict[str, Any]) -> str:
    index = data["index"]
    stocks = data["stocks"]
    index_gate = gate_state(index["current"])
    idx_center = index["geometry_5m"]["center"]
    action_paths = index_action_paths(index)
    lines: list[str] = []
    lines.append(f"# {data['date']} 缠论四层复盘与次日预案")
    lines.append("")
    lines.append("说明：本报告基于本地 5m/30m 高频数据、V10.20 缠论底层逻辑和动量积分递推，仅用于复盘与条件化预案。")
    lines.append("")

    lines.append("## 0. 极简行动版")
    lines.append("")
    cash = safe_float((data.get("account") or {}).get("available_cash"))
    positions = data.get("positions") or {}
    if cash is not None or positions:
        lines.append("### 账户与持仓")
        lines.append("")
        lines.append("```text")
        if cash is not None:
            lines.append(f"可用资金：{cash:.2f}")
        for symbol, pos in positions.items():
            role = pos.get("role") or ("趋势标的" if pos.get("analyze", True) else "只记录")
            analyze_note = "进入趋势复盘" if pos.get("analyze", True) else "不进入趋势复盘"
            lines.append(
                f"{symbol} {pos.get('name') or ''}：{role}，{analyze_note}；"
                f"仓位 {pos.get('position_pct') or '-'}%，成本 {pos.get('cost') or '-'}，"
                f"最新价 {pos.get('last_price') or '-'}，浮盈 {pos.get('profit') or '-'}"
            )
        lines.append("```")
        lines.append("")
    lines.append("```text")
    for line in concise_action_card(index, index_gate=index_gate, is_index=True):
        lines.append(line)
    lines.append("")
    for report in sorted(stocks, key=lambda r: action_rank(classify_symbol(r, index_gate, positions.get(r["symbol"]))[0])):
        for line in concise_action_card(report, index_gate=index_gate, position=positions.get(report["symbol"])):
            lines.append(line)
        lines.append("")
    lines.append("盘中纪律：09:30-10:00 不追买；结构允许 + 回踩VWAP不破 + 大盘总闸不蓝，三者同时满足才进入执行观察。")
    lines.append("```")
    lines.append("")

    market_context = data.get("market_context") or {}
    market_ecology = data.get("market_ecology") or {}
    render_market_ecology(lines, market_ecology, market_context)

    lines.append("## 1. 大盘总闸")
    lines.append("")
    lines.append(
        f"- 上证收盘 {price(index['day']['close'])}，5m活跃中枢 ZD {price(idx_center['ZD'])} / ZG {price(idx_center['ZG'])}，"
        f"当前状态：{index['current']['state']}。"
    )
    lines.append(
        f"- 30m DIF {index['state_30m']['dif']:.3f}，MACD {index['state_30m']['macd']:.3f}，"
        f"近12根DIF斜率 {index['state_30m']['dif_slope_12']:.3f}。"
    )
    lines.append(f"- 总闸颜色：{index_gate}。")
    lines.append(f"- 题材生态：{theme_summary_line(market_ecology)}")
    lines.append("")
    lines.append("```text")
    lines.append("大盘明日总闸")
    lines.append(f"├─ {action_paths['red']['title']}")
    lines.append(f"├─ {action_paths['yellow']['title']}")
    lines.append(f"└─ {action_paths['blue']['title']}")
    lines.append("```")
    lines.append("")
    lines.append(f"- 5m动量递推：{render_projection_line(index['projection_5m'])}")
    lines.append(f"- 30m动量递推：{render_projection_line(index['projection_30m'])}")
    lines.append("")

    lines.append("## 2. 个股四层复盘")
    lines.append("")
    rankings: list[tuple[str, str, str]] = []
    positions = data.get("positions") or {}
    for report in stocks:
        position = positions.get(report["symbol"]) or {}
        action, reason = classify_symbol(report, index_gate, position)
        rankings.append((report["symbol"], action, reason))
        center = report["geometry_5m"]["center"]
        down = report["geometry_5m"]["down_area"]
        rel = report.get("relative_strength") or {}
        exec_state = report["execution"]
        lines.append(f"### {report['symbol']}")
        lines.append("")
        lines.append("```text")
        if position:
            lines.append(
                f"持仓接口：名称 {position.get('name') or '-'}，成本 {position.get('cost') or '-'}，"
                f"仓位 {position.get('position_pct') or '-'}，硬止损 {position.get('hard_stop') or '-'}"
            )
            if position.get("plan_note"):
                lines.append(f"备注：{position['plan_note']}")
        lines.append(f"微观几何：5m中枢 ZD {price(center['ZD'])} / ZG {price(center['ZG'])}，收盘 {price(report['day']['close'])}")
        lines.append(
            f"中枢状态：中枢内有 {report['geometry_5m']['active_center_fractal_count']} 个有效分型，"
            f"九笔扩张警戒：{yes_no(report['geometry_5m']['nine_bi_lifecycle_warning'])}"
        )
        lines.append(f"动能判断：{momentum_area_text(down)}")
        lines.append(f"跨级别：{cross_level_text(report['state_30m'])}")
        if rel:
            lines.append(relative_text(rel))
        lines.append(f"分时锚：{execution_text(exec_state)}")
        lines.append(f"交易类型：{trade_type(position)}")
        lines.append(f"执行结论：{action_label(action)} - {reason}")
        lines.append("```")
        lines.append("")
        lines.append(f"- 5m推演：{render_projection_line(report['projection_5m'])}")
        lines.append(f"- 30m推演：{render_projection_line(report['projection_30m'])}")
        lines.append("")

    lines.append("## 3. 明日行动路径")
    lines.append("")
    lines.append("```text")
    lines.append("明日行动路径")
    lines.append(f"├─ IF {action_paths['red']['title'].replace('红色路径：', '')}")
    for item in action_paths["red"]["items"]:
        lines.append(f"│  ├─ THEN {item}")
    for symbol, action, _reason in sorted(rankings, key=lambda item: action_rank(item[1])):
        if action in {"offense_watch", "strong_but_wait_pullback", "hold_verify"}:
            lines.append(f"│  ├─ {symbol}：{action_label(action)}")
    lines.append(f"├─ IF {action_paths['yellow']['title'].replace('黄色路径：', '')}")
    for item in action_paths["yellow"]["items"]:
        lines.append(f"│  ├─ THEN {item}")
    for symbol, action, _reason in sorted(rankings, key=lambda item: action_rank(item[1])):
        if action in {"range_watch", "repair_or_defense", "alpha_watch", "observe_no_add", "hold_reduce_activity"}:
            lines.append(f"│  ├─ {symbol}：{action_label(action)}")
    lines.append(f"└─ IF {action_paths['blue']['title'].replace('蓝色路径：', '')}")
    for i, item in enumerate(action_paths["blue"]["items"]):
        prefix = "   └─ THEN" if i == 0 else "   ├─ THEN"
        lines.append(f"{prefix} {item}")
    for symbol, action, _reason in sorted(rankings, key=lambda item: action_rank(item[1])):
        if action in {"hold_reduce_activity", "reduce_risk", "observe_no_add"}:
            lines.append(f"   ├─ {symbol}：{action_label(action)}")
    lines.append("```")
    lines.append("")

    lines.append("## 4. 明日优先级")
    lines.append("")
    for i, (symbol, action, reason) in enumerate(sorted(rankings, key=lambda item: action_rank(item[1])), 1):
        lines.append(f"{i}. {symbol}：{action_label(action)}。{reason}")
    lines.append("")
    lines.append("执行纪律：09:30-10:00 不追买；若白线相对VWAP正偏离超过1.5%-2.0%，只允许观察或高抛，不启动新增买入。")
    if data.get("config_path"):
        lines.append(f"持仓/关注列表配置：{data['config_path']}")
    lines.append("")
    return "\n".join(lines)


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def css_class_for_action(action: str) -> str:
    return {
        "offense_watch": "action-offense",
        "strong_but_wait_pullback": "action-wait",
        "alpha_watch": "action-alpha",
        "hold_verify": "action-range",
        "range_watch": "action-range",
        "repair_or_defense": "action-defense",
        "defense": "action-defense",
        "observe_no_add": "action-defense",
        "hold_reduce_activity": "action-wait",
        "reduce_risk": "action-defense",
        "strong_hold_no_add": "action-offense",
    }.get(action, "action-defense")


def css_class_for_gate(gate: str) -> str:
    return {
        "red": "gate-red",
        "yellow": "gate-yellow",
        "blue": "gate-blue",
    }.get(gate, "gate-yellow")


def render_level_pills(report: dict[str, Any]) -> str:
    center = report["geometry_5m"].get("center") or {}
    close = safe_float(report.get("day", {}).get("close"))
    zd = safe_float(center.get("ZD"))
    zg = safe_float(center.get("ZG"))
    vwap = safe_float(report.get("execution", {}).get("vwap"))
    items = [
        ("防守", zd),
        ("中枢上沿", zg),
        ("VWAP", vwap),
        ("收盘", close),
    ]
    return "".join(
        f'<div class="level-pill"><span>{h(label)}</span><strong>{price(value)}</strong></div>'
        for label, value in items
        if value is not None
    )


def today_walk_text(report: dict[str, Any]) -> str:
    center = report.get("geometry_5m", {}).get("center")
    close = safe_float(report.get("day", {}).get("close"))
    pos = center_position(close, center)
    down = report.get("geometry_5m", {}).get("down_area") or {}
    return " ".join(
        [
            f"收盘在5m{pos}。",
            momentum_area_text(down),
            cross_level_text(report.get("state_30m") or {}),
            execution_text(report.get("execution") or {}),
            relative_text(report.get("relative_strength") or {}),
        ]
    )


def stock_plan_text(report: dict[str, Any], index_gate: str, position: dict[str, Any]) -> str:
    lines = concise_action_card(report, index_gate=index_gate, position=position)
    return " ".join(lines[2:5])


def index_overview_text(index: dict[str, Any], index_gate: str) -> str:
    center = index.get("geometry_5m", {}).get("center")
    day = index.get("day") or {}
    state30 = index.get("state_30m") or {}
    proj5 = projection_text(index.get("projection_5m") or {})
    proj30 = projection_text(index.get("projection_30m") or {})
    close = safe_float(day.get("close"))
    pos = center_position(close, center)
    dif = safe_float(state30.get("dif"))
    slope = safe_float(state30.get("dif_slope_12"))
    gate = gate_plain_text(index_gate, index.get("current") or {}, center)
    slope_text = "修复" if slope is not None and slope > 0 else "走弱"
    return (
        f"{gate} 今日上证收 {price(close)}，落在5m{pos}；"
        f"30m DIF {price(dif, 3)}，斜率{slope_text}。"
        f"5m看法：{proj5} 30m看法：{proj30}"
    )


def render_dashboard_market_ecology(ecology: dict[str, Any]) -> str:
    if not ecology.get("available"):
        return f"""
        <div class="market-ecology">
          <b>题材生态</b>
          <p>{h(ecology.get('error') or '未找到全A数据')}</p>
        </div>
        """
    daily = ecology.get("daily") or {}
    themes = "".join(
        f"""
        <div class="theme-chip">
          <strong>{h(row.get('market_theme'))}</strong>
          <span>均涨 {h(pct(safe_float(row.get('avg_pct'))))} · 涨停 {h(row.get('limit_up'))} · 成交 {h(fmt_100m(safe_float(row.get('amount_100m')), 1))}</span>
          <span class="theme-leaders">领涨：{h('、'.join(str(x) for x in (row.get('top_names') or [])[:10]) or '-')}</span>
        </div>
        """
        for row in (ecology.get("theme_mappings") or [])[:4]
    )
    return f"""
    <div class="market-ecology">
      <b>题材生态</b>
      <div class="breadth-grid">
        <span>上涨 {h(daily.get('up'))} / 下跌 {h(daily.get('down'))}</span>
        <span>上涨占比 {h(pct((safe_float(daily.get('up_ratio')) or 0) * 100, 1))}</span>
        <span>中位涨幅 {h(pct(safe_float(daily.get('median_pct'))))}</span>
        <span>主力净额 {h(fmt_100m(safe_float(daily.get('main_net_100m')), 0))}</span>
      </div>
      <p>{h(theme_summary_line(ecology))}</p>
      <div class="theme-grid">{themes}</div>
    </div>
    """


def index_action_paths(index: dict[str, Any]) -> dict[str, dict[str, Any]]:
    center = index.get("geometry_5m", {}).get("center") or {}
    close = safe_float((index.get("day") or {}).get("close"))
    zd = safe_float(center.get("ZD"))
    zg = safe_float(center.get("ZG"))
    proj5 = index.get("projection_5m") or {}
    th = proj5.get("thresholds") or {}
    macd_floor = safe_float(th.get("flat_close_for_macd_improve"))
    dif_floor = safe_float(th.get("next_close_for_dif_above_last_bottom"))
    floors = [x for x in [dif_floor, macd_floor] if x is not None]
    near_support = min(floors) if floors else zd
    support_label = (
        f"{price(near_support)}-{price(max(floors))}"
        if len(floors) >= 2 and min(floors) != max(floors)
        else price(near_support)
    )

    if close is not None and zd is not None and close < zd:
        return {
            "red": {
                "title": f"红色路径：收复 {price(zd)}，再看 {price(zg)}",
                "items": [
                    "先收回5m中枢下沿，系统风险才降级。",
                    "继续收复中枢上沿后，再观察强结构延续。",
                    "不追VWAP正偏离过大的急拉。",
                ],
            },
            "yellow": {
                "title": f"黄色路径：守住 {support_label}",
                "items": [
                    "只按弱修复处理，不把反弹当反转。",
                    "等待5m二买/三买或VWAP承接确认。",
                    "未收回5m中枢下沿前，个股新增信号降级。",
                ],
            },
            "blue": {
                "title": f"蓝色路径：跌破 {price(near_support)}",
                "items": [
                    "全部新增信号降级。",
                    "不新增趋势仓。",
                    "优先控制回撤，等待重新站回近端结构。",
                ],
            },
        }
    if close is not None and zd is not None and zg is not None and close <= zg:
        return {
            "red": {
                "title": f"红色路径：站上 {price(zg)}",
                "items": ["指数站回中枢上沿，系统风险降级。", "只激活强结构个股。", "不追VWAP正偏离过大的急拉。"],
            },
            "yellow": {
                "title": f"黄色路径：守住 {price(zd)}",
                "items": ["只做承接验证。", "等待5m二买/三买，不开盘追价。", "中枢内个股等待方向选择。"],
            },
            "blue": {
                "title": f"蓝色路径：跌破 {price(zd)}",
                "items": ["全部新增信号降级。", "不新增趋势仓。", "优先控制回撤，等待结构确认。"],
            },
        }
    return {
        "red": {
            "title": f"红色路径：守住 {price(zg)}",
            "items": ["指数维持中枢上方，观察延续。", "只激活强结构个股。", "不追VWAP正偏离过大的急拉。"],
        },
        "yellow": {
            "title": f"黄色路径：回踩 {price(zg)}",
            "items": ["回踩上沿不破才算强。", "等待5m承接确认。", "跌回中枢内则降低新增优先级。"],
        },
        "blue": {
            "title": f"蓝色路径：跌回 {price(zd)} 下方",
            "items": ["指数跌回中枢下方，新增信号降级。", "不新增趋势仓。", "优先控制回撤，等待结构确认。"],
        },
    }


def render_dashboard_market_overview(index: dict[str, Any], index_gate: str, ecology: dict[str, Any]) -> str:
    center = index.get("geometry_5m", {}).get("center")
    day = index.get("day") or {}
    state30 = index.get("state_30m") or {}
    close = safe_float(day.get("close"))
    pos = center_position(close, center)
    dif = safe_float(state30.get("dif"))
    slope = safe_float(state30.get("dif_slope_12"))
    slope_text = "修复" if slope is not None and slope > 0 else "走弱"
    gate_text = {
        "red": "偏红：指数站在5m中枢上方，允许验证强结构延续。",
        "yellow": "黄色：指数在5m中枢附近，只做承接验证。",
        "blue": "偏蓝：指数收在5m中枢下方，新增买点降级，个股按结构位和VWAP承接处理。",
    }.get(index_gate, "观察：先看指数中枢位置和承接质量。")
    proj5 = projection_text(index.get("projection_5m") or {})
    proj30 = projection_text(index.get("projection_30m") or {})
    return f"""
    <div class="market-overview">
      <b>大盘总体分析</b>
      <div class="overview-grid">
        <section>
          <strong>结构总闸</strong>
          <span>{h(gate_text)} 上证收 {h(price(close))}，落在5m{h(pos)}。</span>
        </section>
        <section>
          <strong>30m动量</strong>
          <span>DIF {h(price(dif, 3))}，斜率{h(slope_text)}；先看能否修复到中枢下沿附近。</span>
        </section>
        <section>
          <strong>5m推演</strong>
          <span>{h(proj5)}</span>
        </section>
        <section>
          <strong>30m推演</strong>
          <span>{h(proj30)}</span>
        </section>
        <section class="wide">
          <strong>题材生态</strong>
          <span>{h(theme_summary_line(ecology))}</span>
        </section>
        <section class="wide">
          <strong>执行纪律</strong>
          <span>大盘总闸偏蓝时，新增买点降级；只做主线核心回踩承接，不追VWAP正偏离过大的急拉。</span>
        </section>
      </div>
    </div>
    """


def render_stock_card(report: dict[str, Any], index_gate: str) -> str:
    pos = (report.get("position") or {})
    action, reason = classify_symbol(report, index_gate, pos)
    symbol = report["symbol"]
    name = pos.get("name") or symbol
    rel = report.get("relative_strength") or {}
    exec_state = report.get("execution") or {}
    geo = report.get("geometry_5m") or {}
    down = geo.get("down_area") or {}
    proj5 = projection_text(report.get("projection_5m") or {})
    proj30 = projection_text(report.get("projection_30m") or {})
    plan = stock_plan_text(report, index_gate, pos)
    theme = report.get("theme_attribution") or {}
    theme_html = ""
    if theme:
        theme_html = f"""
        <section>
          <b>题材归因</b>
          <span>{h(theme.get('industry'))} -> {h(' / '.join(theme.get('market_themes') or ['未匹配固定题材']))}；置信度 {h(theme.get('confidence') or '-')}。今日 {h(pct(safe_float(theme.get('pct'))))}，成交 {h(fmt_100m(safe_float(theme.get('amount_100m')), 1))}，主力净额 {h(fmt_100m(safe_float(theme.get('main_net_100m')), 1))}。</span>
        </section>
        """
    close = safe_float(report.get("day", {}).get("close"))
    center = geo.get("center")
    pos_label = center_position(close, center)
    state30 = report.get("state_30m") or {}
    slope_text = "向上" if safe_float(state30.get("dif_slope_12")) is not None and safe_float(state30.get("dif_slope_12")) > 0 else "走弱"
    vwap_dev = safe_float(exec_state.get("vwap_dev_pct"))
    takeaway = (
        f"{symbol} {name}：交易类型：{trade_type(pos)}；执行结论：{action_label(action)}。"
        f"收在5m{pos_label}，30m DIF{slope_text}，VWAP偏离 {pct(vwap_dev)}。"
    )
    title = f"{symbol} {name}" if name != symbol else symbol
    return f"""
    <article class="stock-card {css_class_for_action(action)}">
      <div class="card-head">
        <div>
          <h3>{h(title)}</h3>
        </div>
        <span class="action-badge">{h(action_label(action))}</span>
      </div>
      <div class="takeaway">{h(takeaway)}</div>
      <div class="levels">{render_level_pills(report)}</div>
      <div class="stock-sections">
        <section>
          <b>当日走势</b>
          <span>{h(today_walk_text(report))}</span>
        </section>
        <section>
          <b>5m推演</b>
          <span>{h(proj5)} {h(momentum_area_text(down))}</span>
        </section>
        <section>
          <b>30m推演</b>
          <span>{h(proj30)} {h(cross_level_text(report.get("state_30m") or {}))}</span>
        </section>
        {theme_html}
        <section>
          <b>操作计划</b>
          <span>{h(plan)}</span>
        </section>
      </div>
    </article>
    """


def render_dashboard_html(data: dict[str, Any]) -> str:
    index = data["index"]
    stocks = data["stocks"]
    index_gate = gate_state(index["current"])
    idx_center = index["geometry_5m"]["center"]
    positions = data.get("positions") or {}
    market_ecology = data.get("market_ecology") or {}
    action_paths = index_action_paths(index)
    theme_by_symbol = {
        normalize_symbol(str(row.get("code"))): row
        for row in (market_ecology.get("focus_stocks") or [])
        if row.get("code")
    }
    for report in stocks:
        report["position"] = positions.get(report["symbol"]) or {}
        report["theme_attribution"] = theme_by_symbol.get(report["symbol"]) or {}
    ranked = sorted(stocks, key=lambda r: action_rank(classify_symbol(r, index_gate, r.get("position") or {})[0]))

    gate_label = {"red": "偏红：可观察延续", "yellow": "黄色：只做验证", "blue": "偏蓝：全场防守"}.get(index_gate, "观察")
    market_overview_html = render_dashboard_market_overview(index, index_gate, market_ecology)
    market_ecology_html = render_dashboard_market_ecology(market_ecology)

    stock_cards = "\n".join(render_stock_card(report, index_gate) for report in ranked)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{h(data['date'])} 缠论复盘看板</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d9e0ea;
      --red: #d92d20;
      --green: #16865a;
      --blue: #245985;
      --amber: #b7791f;
      --shadow: 0 10px 28px rgba(31, 45, 61, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      line-height: 1.45;
    }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 22px; }}
    .hero {{ margin-bottom: 16px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: 24px; }}
    .subtitle {{ color: var(--muted); margin: 0; }}
    .gate-red {{ background: #fff1ef; border-color: #ffc9c3; }}
    .gate-yellow {{ background: #fff8e8; border-color: #efd08d; }}
    .gate-blue {{ background: #eef5ff; border-color: #bfd7fb; }}
    .market-overview {{ margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdff; }}
    .market-overview b {{ display: block; margin-bottom: 5px; font-size: 14px; }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }}
    .overview-grid section {{ border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #ffffff; }}
    .overview-grid section.wide {{ grid-column: span 2; }}
    .overview-grid strong {{ display: block; font-size: 13px; margin-bottom: 4px; }}
    .overview-grid span {{ display: block; color: #344054; font-size: 13px; }}
    .market-ecology {{ margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #ffffff; }}
    .market-ecology b {{ display: block; margin-bottom: 8px; font-size: 14px; }}
    .market-ecology p {{ margin: 8px 0; color: #344054; font-size: 13px; }}
    .breadth-grid, .theme-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .breadth-grid span, .theme-chip {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #f8fafc; }}
    .theme-chip strong {{ display: block; font-size: 13px; }}
    .theme-chip span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .theme-leaders {{ color: #344054 !important; }}
    .section-title {{ margin: 22px 0 10px; font-size: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }}
    .stock-card {{ background: var(--panel); border: 1px solid var(--line); border-top: 5px solid var(--blue); border-radius: 8px; padding: 14px; box-shadow: var(--shadow); }}
    .action-wait {{ border-top-color: var(--amber); }}
    .action-offense {{ border-top-color: var(--green); }}
    .action-range {{ border-top-color: var(--blue); }}
    .action-defense {{ border-top-color: #8a94a6; }}
    .card-head {{ display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }}
    .card-head h3 {{ margin: 0; font-size: 18px; }}
    .card-head p {{ margin: 4px 0 0; color: var(--muted); font-size: 12px; }}
    .action-badge {{ white-space: nowrap; border-radius: 999px; padding: 4px 9px; background: #eef3f8; color: #1f4e79; font-size: 12px; font-weight: 800; }}
    .takeaway {{ margin: 12px 0; padding: 10px; background: #f8fafc; border-radius: 8px; border: 1px solid var(--line); font-weight: 700; }}
    .levels {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 10px 0; }}
    .level-pill {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px; }}
    .level-pill span {{ display: block; color: var(--muted); font-size: 12px; }}
    .level-pill strong {{ font-size: 16px; }}
    .stock-sections {{ display: grid; gap: 8px; }}
    .stock-sections section {{ border-top: 1px solid var(--line); padding-top: 8px; }}
    .stock-sections b {{ display: block; font-size: 13px; margin-bottom: 3px; }}
    .stock-sections span, .reason {{ color: #344054; font-size: 13px; }}
    .reason {{ margin: 10px 0 0; }}
    .tree {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }}
    .top-tree {{ margin-top: 12px; }}
    .path {{ border-radius: 8px; padding: 12px; border: 1px solid var(--line); background: var(--panel); }}
    .path h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .path ul {{ margin: 0; padding-left: 18px; color: #344054; }}
    .skip-row {{ display: grid; grid-template-columns: 1.4fr 1fr 1fr 1fr; gap: 10px; padding: 10px 0; border-top: 1px solid var(--line); }}
    .empty {{ color: var(--muted); padding: 10px 0; }}
    footer {{ color: var(--muted); margin: 22px 0 4px; font-size: 12px; }}
    @media (max-width: 920px) {{
      .page {{ padding: 14px; }}
      .cards, .tree, .overview-grid {{ grid-template-columns: 1fr; }}
      .overview-grid section.wide {{ grid-column: auto; }}
      .levels {{ grid-template-columns: 1fr 1fr; }}
      .skip-row {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 520px) {{
      .levels {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="panel">
        <h1>{h(data['date'])} 缠论复盘看板</h1>
        <p class="subtitle">先看大盘和题材生态，再看标的动作。Markdown 和 JSON 仍保留作归档。</p>
        {market_overview_html}
        {market_ecology_html}
        <h2 class="section-title">明日行动路径</h2>
        <section class="tree top-tree">
          <div class="path gate-red">
            <h3>{h(action_paths['red']['title'])}</h3>
            <ul>
              {''.join(f"<li>{h(item)}</li>" for item in action_paths['red']['items'])}
            </ul>
          </div>
          <div class="path gate-yellow">
            <h3>{h(action_paths['yellow']['title'])}</h3>
            <ul>
              {''.join(f"<li>{h(item)}</li>" for item in action_paths['yellow']['items'])}
            </ul>
          </div>
          <div class="path gate-blue">
            <h3>{h(action_paths['blue']['title'])}</h3>
            <ul>
              {''.join(f"<li>{h(item)}</li>" for item in action_paths['blue']['items'])}
            </ul>
          </div>
        </section>
      </div>
    </section>

    <h2 class="section-title">趋势持仓复盘</h2>
    <section class="cards">{stock_cards}</section>

    <footer>生成自 tools/chanlun_replay_plan.py；数据源：本地 D:\\OneDrive\\Stock\\details。</footer>
  </main>
</body>
</html>"""


def build_data(index: str, symbols: list[str]) -> dict[str, Any]:
    index = normalize_symbol(index)
    symbols = [normalize_symbol(s) for s in symbols]
    index_df = load_frame(index, "5m")
    index_report = build_symbol_report(index, index_df)
    stock_reports = [build_symbol_report(symbol, index_df) for symbol in symbols]
    report_date = index_report["day"]["date"]
    return {
        "date": report_date,
        "index_symbol": index,
        "symbols": symbols,
        "index": index_report,
        "stocks": stock_reports,
        "model": {
            "quantum_buffer": QUANTUM_BUFFER,
            "momentum_threshold": MOMENTUM_THRESHOLD,
            "engine": "chanlun_v10_20_core.analyze_frame_original",
        },
    }


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def config_symbols(config: dict[str, Any]) -> list[str]:
    items = config.get("symbols")
    if not items:
        return DEFAULT_SYMBOLS
    if all(isinstance(item, str) for item in items):
        return [str(item) for item in items]
    result = []
    for item in items:
        if isinstance(item, dict) and item.get("symbol"):
            if item.get("analyze") is False:
                continue
            result.append(str(item["symbol"]))
    return result or DEFAULT_SYMBOLS


def config_positions(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    positions: dict[str, dict[str, Any]] = {}
    for item in config.get("symbols", []) or []:
        if not isinstance(item, dict) or not item.get("symbol"):
            continue
        symbol = normalize_symbol(str(item["symbol"]))
        positions[symbol] = {
            "name": item.get("name"),
            "shares": item.get("shares"),
            "available_shares": item.get("available_shares"),
            "market_value": item.get("market_value"),
            "cost": item.get("cost"),
            "last_price": item.get("last_price"),
            "position_pct": item.get("position_pct"),
            "profit_pct": item.get("profit_pct"),
            "profit": item.get("profit"),
            "hard_stop": item.get("hard_stop"),
            "plan_note": item.get("plan_note"),
            "role": item.get("role"),
            "analyze": item.get("analyze", True),
        }
    return positions


def main() -> int:
    parser = argparse.ArgumentParser(description="Chanlun four-layer replay and next-day action tree.")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="Index symbol, default sh000001.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="Stock symbols.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Optional watchlist/position JSON config.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory.")
    parser.add_argument("--json", action="store_true", help="Also print compact JSON to stdout.")
    args = parser.parse_args()

    config = load_config(args.config)
    index = config.get("index", args.index)
    symbols = config_symbols(config) if config else args.symbols
    data = build_data(index, symbols)
    positions = config_positions(config)
    data["config_path"] = str(args.config) if args.config else None
    data["positions"] = positions
    data["account"] = config.get("account", {})
    data["market_context"] = config.get("market_context", {})
    focus_symbols = sorted(set(symbols) | set(positions.keys()))
    data["market_ecology"] = build_market_ecology(data["date"], focus_symbols)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    date_slug = str(data["date"]).replace("-", "")
    md_path = args.out_dir / f"{date_slug}_chanlun_replay_plan.md"
    json_path = args.out_dir / f"{date_slug}_chanlun_replay_plan.json"
    html_path = args.out_dir / f"{date_slug}_chanlun_dashboard.html"
    md_path.write_text(render_report(data), encoding="utf-8-sig")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_dashboard_html(data), encoding="utf-8-sig")

    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    if args.json:
        print(json.dumps({"markdown": str(md_path), "json": str(json_path), "html": str(html_path), "date": data["date"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
