from __future__ import annotations

import argparse
import html
import json
import math
import re
import sqlite3
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
REPLIES_DIR = Path(r"D:\OneDrive\Stock\Replies collect")
DAILY_REVIEW_DIR = Path(r"D:\OneDrive\Stock\Daily review")
DEFAULT_INDEX = "sh000001"
DEFAULT_SYMBOLS: list[str] = []
DEFAULT_OUT_DIR = REPLAY_ROOT / "plans"
DEFAULT_CONFIG = REPLAY_ROOT / "plans" / "watchlist_config.json"
DEFAULT_CLOUD_HTML_DIR = Path(r"D:\OneDrive\Stock\Daily review")
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
    {
        "official_industries": ["锂"],
        "market_theme": "锂矿 / 锂盐 / 电池材料",
        "confidence": "中高",
        "reading": "资源品事件驱动和价格预期修复并存，强势日不追一致，优先等分歧后的承接。",
    },
    {
        "official_industries": ["钨钼", "其他金属", "铅锌", "铜", "钛"],
        "market_theme": "小金属 / 有色资源",
        "confidence": "中",
        "reading": "弱市里的资源抱团方向，先看持续性和成交承接，不把首日强度直接当主升。",
    },
    {
        "official_industries": ["磷肥及磷化工", "氟化工"],
        "market_theme": "磷化工 / 氟化工 / 化工材料",
        "confidence": "中",
        "reading": "材料分支偏事件和价格预期驱动，重点观察前排是否继续扩散。",
    },
    {
        "official_industries": ["玻纤制造"],
        "market_theme": "玻纤 / 复合材料",
        "confidence": "中",
        "reading": "材料侧轮动方向，只有放量扩散并出现容量核心时才提高优先级。",
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


def industry_leader_names(valid: pd.DataFrame, industry: str) -> list[str]:
    subset = valid[valid["industry"] == industry].copy()
    if subset.empty:
        return []
    return leader_names(subset)


def industry_records(frame: pd.DataFrame, valid: pd.DataFrame) -> list[dict[str, Any]]:
    rows = plain_records(frame)
    for row in rows:
        row["top_names"] = industry_leader_names(valid, str(row.get("industry") or ""))
    return rows


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
    top_avg_records = industry_records(top_avg, valid)
    top_amount_records = industry_records(top_amount, valid)

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
        "top_industries_by_avg": top_avg_records,
        "top_industries_by_amount": top_amount_records,
        "theme_mappings": theme_rows,
        "focus_stocks": stock_rows,
        "summary": market_ecology_summary(daily, theme_rows, top_avg_records),
    }


def market_ecology_summary(
    daily: dict[str, Any],
    theme_rows: list[dict[str, Any]],
    top_industries: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
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
    strong = [
        str(row.get("industry"))
        for row in (top_industries or [])
        if (safe_float(row.get("avg_pct")) or -99) > 0
        and ((safe_float(row.get("gt5")) or 0) > 0 or (safe_float(row.get("limit_up")) or 0) > 0)
    ][:6]
    if strong:
        mainline = " / ".join(strong)
    else:
        top_themes = [row["market_theme"] for row in theme_rows[:3] if (safe_float(row.get("avg_pct")) or -99) > 0]
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
        judgment = report.get("judgment") or {}
        action_paths = final_index_action_paths(report, judgment)
        red_gate = action_paths["red"]["title"].replace("红色路径：", "")
        yellow_gate = action_paths["yellow"]["title"].replace("黄色路径：", "")
        blue_gate = action_paths["blue"]["title"].replace("蓝色路径：", "")
        summary_text = str(judgment.get("summary") or "").strip()
        structure_text = str(judgment.get("structure") or "").strip()
        lines.append(f"{report['symbol']}：{summary_text or gate_plain_text(index_gate, report.get('current') or {}, center)}")
        lines.append(f"今日结构：{structure_text or f'收盘 {price(close)}，位置在5m{pos}，30m DIF{slope_text}。'}")
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
        f"今日强势方向：{summary.get('mainline') or '未识别'}。"
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


def render_expert_digest(lines: list[str], digest: dict[str, Any]) -> None:
    if not digest:
        return
    lines.append("## 0.2 跟踪对象发言精炼")
    lines.append("")
    lines.append("```text")
    lines.append(f"盘面颜色：{digest.get('market_color') or '未填写'}")
    lines.append(f"交易类型：{digest.get('trade_type') or '未填写'}")
    lines.append(f"主线焦点：{digest.get('main_focus') or '未填写'}")
    lines.append(f"执行结论：{digest.get('execution') or '未填写'}")
    lines.append("```")
    lines.append("")
    for label, key in [("共识", "consensus"), ("分歧", "divergence"), ("风险", "risk"), ("明日", "tomorrow")]:
        value = digest.get(key)
        if value:
            lines.append(f"- {label}：{value}")
    filters = digest.get("filters") or []
    if filters:
        lines.append("")
        lines.append("明日过滤器：")
        for item in filters:
            lines.append(f"- {item}")
    quotes = digest.get("quotes") or []
    if quotes:
        lines.append("")
        lines.append("重点发言摘抄：")
        for item in quotes:
            tag = item.get("tag") or "摘抄"
            source = item.get("source") or "跟踪对象"
            quote = item.get("quote") or ""
            takeaway = item.get("takeaway") or ""
            lines.append(f"- [{tag}] {source}：{quote} -> {takeaway}")
    if digest.get("source"):
        lines.append("")
        lines.append(f"来源：`{digest.get('source')}`")
    lines.append("")


def render_report(data: dict[str, Any]) -> str:
    index = data["index"]
    stocks = data["stocks"]
    index_gate = gate_state(index["current"])
    idx_center = index["geometry_5m"]["center"]
    index["judgment"] = data.get("index_judgment") or {}
    action_paths = final_index_action_paths(index, data.get("index_judgment"))
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
        lines.append("### 复盘对象")
        lines.append("")
        lines.append("```text")
        if cash is not None:
            lines.append(f"可用资金：{cash:.2f}")
        for symbol, pos in positions.items():
            role = pos.get("role") or ("趋势标的" if pos.get("analyze", True) else "只记录")
            analyze_note = "进入趋势复盘" if pos.get("analyze", True) else "不进入趋势复盘"
            note = f"；{pos.get('plan_note')}" if pos.get("plan_note") else ""
            lines.append(f"{symbol} {pos.get('name') or ''}：{role}，{analyze_note}{note}")
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
    render_expert_digest(lines, data.get("expert_digest") or {})

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
        judgment = (data.get("stock_judgments") or {}).get(report["symbol"]) or {}
        report["judgment"] = judgment
        lines.append(f"### {report['symbol']}")
        lines.append("")
        lines.append("```text")
        if position:
            role = position.get("role") or ("趋势标的" if position.get("analyze", True) else "只记录")
            lines.append(f"复盘配置：名称 {position.get('name') or '-'}，角色 {role}")
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
    lines.append("执行纪律：新增买入只过结构、情绪/主线两道过滤；结构未确认或不在主线核心时，只观察。")
    if data.get("config_path"):
        lines.append(f"持仓/关注列表配置：{data['config_path']}")
    lines.append("")
    return "\n".join(lines)


def h(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def clean_html_text(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_quote_text(fragment: str) -> str:
    return clean_html_text(fragment).strip("“”")


def read_expert_dashboard(report_date: str, base_dir: Path = REPLIES_DIR) -> dict[str, Any]:
    compact_date = str(report_date).replace("-", "")
    path = base_dir / f"今日总结看板_{compact_date}.html"
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    digest: dict[str, Any] = {
        "source_dashboard": str(path),
        "selection_rule": "保留能转化为交易含义和明日动作的摘录；只表达情绪、闲聊或无法对应主线/风险/执行的内容不进入看板。",
    }

    metric_rows = []
    for block in re.findall(r'<div class="metric">(.*?)</div></div>', raw, flags=re.S):
        label = re.search(r'<div class="label">(.*?)</div>', block, flags=re.S)
        value = re.search(r'<div class="value">(.*?)</div>', block, flags=re.S)
        hint = re.search(r'<div class="hint">(.*?)</div>', block, flags=re.S)
        if label and value:
            metric_rows.append(
                {
                    "label": clean_html_text(label.group(1)),
                    "value": clean_html_text(value.group(1)),
                    "hint": clean_html_text(hint.group(1)) if hint else "",
                }
            )
    if metric_rows:
        digest["metrics"] = metric_rows
        by_label = {item["label"]: item for item in metric_rows}
        digest["market_color"] = by_label.get("盘面颜色", {}).get("value")
        digest["trade_type"] = by_label.get("交易类型", {}).get("value")
        digest["main_focus"] = by_label.get("主线焦点", {}).get("value")
        digest["execution"] = by_label.get("执行结论", {}).get("value")

    decisions = []
    for label, text in re.findall(r'<div class="decision-row"><b>(.*?)</b><p>(.*?)</p></div>', raw, flags=re.S):
        decisions.append({"label": clean_html_text(label), "text": clean_html_text(text)})
    if decisions:
        digest["decisions"] = decisions
        for item in decisions:
            key = {"共识": "consensus", "分歧": "divergence", "风险": "risk", "明日": "tomorrow"}.get(item["label"])
            if key:
                digest[key] = item["text"]

    briefs = []
    for title, text in re.findall(r'<div class="brief-card"><strong>(.*?)</strong><span>(.*?)</span></div>', raw, flags=re.S):
        briefs.append({"title": clean_html_text(title), "text": clean_html_text(text)})
    if briefs:
        digest["briefs"] = briefs
        digest["filters"] = [f"{item['title']}：{item['text']}" for item in briefs]

    heat = []
    for label, level in re.findall(r'<div class="bar-line"><span>(.*?)</span>.*?<b>(.*?)</b></div>', raw, flags=re.S):
        heat.append({"label": clean_html_text(label), "level": clean_html_text(level)})
    if heat:
        digest["theme_heat"] = heat

    for section_title, key in [("机会线索", "opportunities"), ("风险线索", "risk_lines")]:
        match = re.search(rf'<h2>{section_title}</h2>\s*<ul class="list">(.*?)</ul>', raw, flags=re.S)
        if match:
            digest[key] = [clean_html_text(item) for item in re.findall(r"<li>(.*?)</li>", match.group(1), flags=re.S)]

    quotes = []
    for block in re.findall(r'<article class="quote-card">(.*?)</article>', raw, flags=re.S):
        tag_match = re.search(r'<span class="badge [^"]+">(.*?)</span>', block, flags=re.S)
        source_match = re.search(r'<div class="quote-meta">.*?</span><span>(.*?)</span></div>', block, flags=re.S)
        quote_match = re.search(r"<blockquote>(.*?)</blockquote>", block, flags=re.S)
        context_match = re.search(r'<div class="context">(.*?)</div>', block, flags=re.S)
        takeaway_match = re.search(r'<div class="takeaway">(.*?)</div>', block, flags=re.S)
        action_match = re.search(r'<div class="action">(.*?)</div>', block, flags=re.S)
        url_match = re.search(r'<a href="([^"]+)"', block, flags=re.S)
        if quote_match:
            quotes.append(
                {
                    "tag": clean_html_text(tag_match.group(1)) if tag_match else "摘录",
                    "source": clean_html_text(source_match.group(1)) if source_match else "跟踪对象",
                    "quote": clean_quote_text(quote_match.group(1)),
                    "context": clean_html_text(context_match.group(1)).replace("背景：", "", 1) if context_match else "",
                    "takeaway": clean_html_text(takeaway_match.group(1)).replace("交易含义：", "", 1) if takeaway_match else "",
                    "action": clean_html_text(action_match.group(1)).replace("明日动作：", "", 1) if action_match else "",
                    "url": html.unescape(url_match.group(1)) if url_match else "",
                }
            )
    if quotes:
        digest["quotes"] = quotes
    return digest


def markdown_blocks(raw: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    author_blocks = re.finditer(
        r"(?ms)^###\s+(.+?)\n(.*?)(?=^###\s+|\Z)",
        raw,
    )
    for author_block in author_blocks:
        source = author_block.group(1).strip()
        author_text = author_block.group(2)
        entry_blocks = re.finditer(
            r"(?ms)^####\s+\d+\.\s+(.+?)\n(.*?)(?=^####\s+\d+\.|\Z)",
            author_text,
        )
        for entry_block in entry_blocks:
            heading_time = entry_block.group(1).strip()
            body_text = entry_block.group(2).strip()
            meta_match = re.search(
                r"^>\s*([0-9:\-\s]+)\s*｜.*?\[查看原帖\]\((https?://[^\s)]+)\)",
                body_text,
                flags=re.M,
            )
            body = re.sub(r"(?m)^>\s.*$", "", body_text)
            body = re.sub(r"(?m)^\*\*速览：\*\*\s*", "", body)
            body = re.sub(r"(?m)^---\s*$", "", body)
            body = body.strip()
            result.append(
                {
                    "source": source,
                    "time": (meta_match.group(1).strip() if meta_match else heading_time),
                    "url": meta_match.group(2).strip() if meta_match else "",
                    "body": body,
                }
            )
    return result


def useful_quote_from_body(body: str) -> str:
    keywords = ["AI", "科技", "涨价", "半导体", "PCB", "CPO", "光模块", "锂", "指数", "熊", "老登", "主线", "核心", "仓位", "不买", "保护", "调仓", "频繁交易", "震荡"]
    noise = ["大道老师好", "查看图片", "回复", "无标题", "朋友发的", "谢谢你啊", "我去康康怎么个事", "在哪赚一个点都是一样的"]
    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip()
        and not line.strip().startswith("$")
        and line.strip() not in {"回复", "查看图片", "//"}
        and not line.strip().startswith("@")
        and not line.strip().startswith("Reply to ")
        and not line.strip().startswith("引用：")
        and not any(item in line.strip() for item in noise)
    ]
    if not lines:
        return ""
    text = " ".join(lines)
    sentences = re.split(r"(?<=[。！？!?])\s*", text)
    candidates = [item.strip() for item in sentences if len(item.strip()) >= 6]
    keyword_candidates = [item for item in candidates if any(key in item for key in keywords)]
    quote = keyword_candidates[0] if keyword_candidates else (candidates[0] if candidates else text)
    return quote[:72]


def quote_reading(body: str) -> tuple[str, str, str]:
    text = body.lower()
    if any(key in body for key in ["AI", "科技", "涨价", "半导体", "PCB", "CPO", "光模块"]):
        return (
            "主线",
            "科技链仍是跟踪对象讨论核心，但资金更挑剔，后排和弱承接不能当主线。",
            "只看核心和有承接的涨价/硬逻辑方向，不追情绪一致。"
        )
    if any(key in body for key in ["仓位", "卖", "加回", "调仓", "不买", "频繁交易"]):
        return (
            "执行",
            "弱震荡里交易节奏比观点更重要，频繁切换和追涨容易把利润吐回去。",
            "先给仓位和交易类型贴标签，等承接或放量确认后再动。"
        )
    if any(key in body for key in ["指数", "熊", "老登", "风险", "见顶", "不会马上熊"]):
        return (
            "风险",
            "指数和体感可能继续分化，不能把局部反弹理解成系统性进攻。",
            "新增买点降级，优先保护本金和核心仓位。"
        )
    if any(key in body for key in ["核心", "保护", "赛道", "etf"]):
        return (
            "核心",
            "弱市里仍然强调核心资产和细分赛道保护，杂毛容错率低。",
            "只做核心，不做无板块地位的打野。"
        )
    if "港股" in body or "百济" in body or "泡泡" in body:
        return (
            "映射",
            "跟踪对象在讨论跨市场仓位切换，反映震荡市中更重确定性和业绩兑现。",
            "A股只借鉴节奏，不直接映射为买点。"
        )
    return (
        "观察",
        "该摘录有助于理解今日情绪，但需要结合结构和板块承接再落到交易。",
        "只作为辅助证据，不单独触发交易。"
    )


def read_expert_markdown_digest(report_date: str, base_dir: Path = REPLIES_DIR) -> dict[str, Any]:
    path = base_dir / "今日汇总.md"
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    updated_match = re.search(r"更新时间：([^\n]+)", raw)
    updated_at = updated_match.group(1).strip() if updated_match else ""
    if str(report_date) not in updated_at:
        return {}
    keywords = ["AI", "科技", "涨价", "半导体", "PCB", "CPO", "光模块", "锂", "指数", "熊", "老登", "主线", "核心", "仓位", "不买", "保护", "调仓", "频繁交易", "震荡"]
    quotes = []
    seen_quotes: set[tuple[str, str]] = set()
    for block in markdown_blocks(raw):
        body = block["body"]
        if not any(key in body for key in keywords):
            continue
        quote = useful_quote_from_body(body)
        if not quote or len(quote) < 8:
            continue
        dedupe_key = (block["source"], quote)
        if dedupe_key in seen_quotes:
            continue
        seen_quotes.add(dedupe_key)
        tag, takeaway, action = quote_reading(body)
        quotes.append(
            {
                "tag": tag,
                "source": f"{block['source']} · {block['time'][11:16] if len(block['time']) >= 16 else ''}".strip(" ·"),
                "quote": quote,
                "context": "来自今日高手发言原始汇总，尚未经过高手总结看板二次精选。",
                "takeaway": takeaway,
                "action": action,
                "url": block["url"],
            }
        )
        if len(quotes) >= 12:
            break
    if not quotes:
        return {}
    return {
        "source": str(path),
        "updated_at": updated_at,
        "market_color": "待精炼",
        "trade_type": "防守等确认",
        "main_focus": "科技核心 / 涨价线 / 风险控制",
        "execution": "只做核心，等承接",
        "consensus": "今日高手笔记已更新，但尚未生成正式总结看板；临时摘录显示讨论重点仍围绕科技核心、涨价线、仓位节奏和风险控制。",
        "divergence": "趋势观点仍看核心科技和涨价线，交易层面更强调震荡市节奏、仓位切换和不要频繁追涨。",
        "risk": "没有正式高手总结看板前，发言只作为辅助证据；最终买卖仍以指数结构、全市场题材生态和个股承接为准。",
        "tomorrow": "先看指数结构和核心方向承接；没有承接不扩大仓位。",
        "filters": [
            "未生成正式高手总结看板时，临时摘录只作辅助，不替代盘面结论。",
            "只做核心，后排和杂毛不因单条发言升级。",
            "新增买入只过结构、情绪/主线两道过滤。",
            "全A题材文件缺失时，题材生态不使用旧数据冒充。"
        ],
        "selection_rule": "复盘直接从今日汇总中筛选能对应主线、风险、仓位和明日动作的摘录；若已有今日总结看板，只作为辅助参考，不作为前置依赖。",
        "quotes": quotes,
    }


def read_marked_expert_evidence(report_date: str) -> dict[str, Any]:
    db_path = REPLAY_ROOT / "data" / "forum_watchlist.sqlite"
    if not db_path.exists():
        return {}
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                posts.id,
                posts.url,
                posts.title,
                posts.content,
                posts.published_at,
                posts.crawled_at,
                sites.name AS site_name,
                watch_targets.display_name AS author_name,
                watch_targets.style,
                post_marks.useful,
                post_marks.refine
            FROM posts
            JOIN sites ON sites.id = posts.site_id
            JOIN watch_targets ON watch_targets.id = posts.target_id
            JOIN post_marks ON post_marks.post_id = posts.id
            WHERE watch_targets.enabled = 1
              AND sites.enabled = 1
              AND post_marks.noise = 0
              AND post_marks.useful = 1
              AND substr(COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at), 1, 10) = ?
            ORDER BY post_marks.useful DESC,
                     COALESCE(NULLIF(posts.published_at, ''), posts.crawled_at) DESC,
                     posts.id DESC
            LIMIT 20
            """,
            (str(report_date),),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        if conn is not None:
            conn.close()
    if not rows:
        return {}

    quotes = []
    for row in rows:
        content = str(row["content"] or "").strip()
        quote = useful_quote_from_body(content) or content[:72]
        tag = "有用"
        source_time = str(row["published_at"] or row["crawled_at"] or "")
        source = f"{row['site_name']} / {row['author_name']}"
        if len(source_time) >= 16:
            source = f"{source} · {source_time[11:16]}"
        quotes.append(
            {
                "tag": tag,
                "source": source,
                "quote": quote,
                "context": "来自阅读中心的人工标记证据池；已排除噪音。",
                "takeaway": "人工认为这条发言对复盘有价值，AI总结阶段应优先参考，但仍需结合盘面结构确认。",
                "action": "作为高手观点证据进入复盘，不单独触发交易。",
                "url": row["url"] or "",
            }
        )
    return {
        "source_marked_evidence": str(db_path),
        "selection_rule": "人工标记证据池优先：只纳入有用，排除噪音；AI复盘阶段基于这些人工筛选内容再总结。",
        "quotes": quotes,
    }


def merged_expert_digest(config_digest: dict[str, Any], report_date: str, curated_digest: dict[str, Any] | None = None) -> dict[str, Any]:
    markdown_digest = read_expert_markdown_digest(report_date)
    dashboard_digest = read_expert_dashboard(report_date)
    marked_digest = read_marked_expert_evidence(report_date)
    config_updated_at = str((config_digest or {}).get("updated_at") or "")
    config_matches = str(report_date) in config_updated_at
    curated = curated_digest or {}
    curated_updated_at = str(curated.get("updated_at") or curated.get("date") or "")
    curated_matches = bool(curated) and (not curated_updated_at or str(report_date) in curated_updated_at)
    if not markdown_digest and not dashboard_digest and not config_matches and not curated_matches:
        return {}

    merged = dict(dashboard_digest or {})
    if markdown_digest:
        merged.update({key: value for key, value in markdown_digest.items() if value not in (None, "", [])})
    if marked_digest:
        existing_quotes = list(merged.get("quotes") or [])
        marked_quotes = list(marked_digest.get("quotes") or [])
        merged.update({key: value for key, value in marked_digest.items() if key != "quotes" and value not in (None, "", [])})
        merged["quotes"] = marked_quotes + existing_quotes
    if config_matches:
        merged.update({key: value for key, value in (config_digest or {}).items() if value not in (None, "", [])})
    if curated_matches:
        merged.update({key: value for key, value in curated.items() if value not in (None, "", [])})
    if dashboard_digest:
        merged.setdefault("source_reference_dashboard", dashboard_digest.get("source_dashboard") or dashboard_digest.get("source"))
    return merged


def read_ai_judgment(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


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


def dashboard_stock_summary_text(report: dict[str, Any], action: str) -> str:
    judgment = report.get("judgment") or {}
    if judgment.get("summary"):
        return str(judgment.get("summary"))
    center = report.get("geometry_5m", {}).get("center")
    close = safe_float(report.get("day", {}).get("close"))
    pos = center_position(close, center)
    state30 = report.get("state_30m") or {}
    slope = safe_float(state30.get("dif_slope_12"))
    slope_text = "向上修复" if slope is not None and slope > 0 else "继续走弱"
    execution = report.get("execution") or {}
    vwap = safe_float(execution.get("vwap"))
    vwap_dev = safe_float(execution.get("vwap_dev_pct"))
    return (
        f"收盘在5m{pos}，30m DIF{slope_text}，收盘相对VWAP {pct(vwap_dev)}。"
        f"当前结论是{action_label(action)}；明日先看 {price(vwap)} 附近能否承接，不把急拉当买点。"
    )


def dashboard_stock_structure_text(report: dict[str, Any]) -> str:
    judgment = report.get("judgment") or {}
    if judgment.get("structure"):
        return str(judgment.get("structure"))
    center = report.get("geometry_5m", {}).get("center") or {}
    zd = safe_float(center.get("ZD"))
    zg = safe_float(center.get("ZG"))
    if zd is None or zg is None:
        return "5m中枢边界暂不完整，先按VWAP和日内承接质量观察。没有清晰结构位前，不做主动加仓。"
    return (
        f"关键区间看 {price(zd)} 到 {price(zg)}：站上 {price(zg)} 才转强，跌破 {price(zd)} 转弱。"
        "若仍在区间内，只等方向选择和回踩确认。"
    )


def dashboard_stock_theme_plan_text(
    report: dict[str, Any],
    index_gate: str,
    position: dict[str, Any],
    reason: str,
) -> str:
    judgment = report.get("judgment") or {}
    if judgment.get("theme_plan"):
        return str(judgment.get("theme_plan"))
    theme = report.get("theme_attribution") or {}
    lines = concise_action_card(report, index_gate=index_gate, position=position)
    plan = " ".join(lines[2:4])
    if theme:
        themes = " / ".join(theme.get("market_themes") or ["未匹配固定题材"])
        theme_text = (
            f"题材归因：{theme.get('industry') or '-'} -> {themes}，今日 {pct(safe_float(theme.get('pct')))}，"
            f"主力净额 {fmt_100m(safe_float(theme.get('main_net_100m')), 1)}。"
        )
    else:
        theme_text = "题材归因暂未匹配到全市场强势方向，先按个股结构处理。"
    return f"{theme_text} 执行上{reason}；{plan}"


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
    strong_directions = "".join(
        f"""
        <div class="theme-chip strong-theme">
          <strong>{h(row.get('industry'))}</strong>
          <span>均涨 {h(pct(safe_float(row.get('avg_pct'))))} · 涨停 {h(row.get('limit_up'))} · >=5% {h(row.get('gt5'))} · 成交 {h(fmt_100m(safe_float(row.get('amount_100m')), 1))}</span>
          <span class="theme-leaders">领涨：{h('、'.join(str(x) for x in (row.get('top_names') or [])[:8]) or '-')}</span>
        </div>
        """
        for row in (ecology.get("top_industries_by_avg") or [])[:6]
        if (safe_float(row.get("avg_pct")) or -99) > 0
    )
    watch_chains = "".join(
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
      <strong class="subhead">今日强势方向</strong>
      <div class="theme-grid">{strong_directions}</div>
      <strong class="subhead">高成交链条观察</strong>
      <div class="theme-grid secondary-theme-grid">{watch_chains}</div>
    </div>
    """


def heat_width(level: str) -> int:
    if "高" in level:
        return 82
    if "活跃" in level:
        return 58
    if "弱" in level:
        return 34
    return 50


def render_expert_quote_cards(digest: dict[str, Any]) -> str:
    return "".join(
        f"""
        <article class="quote-card">
          <div class="quote-meta"><span>{h(item.get('tag') or '摘抄')}</span><small>{h(item.get('source') or '跟踪对象')}</small></div>
          <blockquote>{h('“' + str(item.get('quote') or '-') + '”')}</blockquote>
          {f'<p><b>背景：</b>{h(item.get("context"))}</p>' if item.get("context") else ''}
          {f'<p><b>交易含义：</b>{h(item.get("takeaway"))}</p>' if item.get("takeaway") else ''}
          {f'<p><b>明日动作：</b>{h(item.get("action"))}</p>' if item.get("action") else ''}
          {f'<a href="{h(item.get("url"))}">查看原帖</a>' if item.get("url") else ''}
        </article>
        """
        for item in (digest.get("quotes") or [])
    )


def render_dashboard_expert_digest(digest: dict[str, Any]) -> str:
    if not digest:
        return ""
    metrics = digest.get("metrics") or [
        {"label": "盘面结论", "value": digest.get("market_color") or "-", "hint": digest.get("consensus") or ""},
        {"label": "交易类型", "value": digest.get("trade_type") or "-", "hint": "先分交易类型，再决定处理方式。"},
        {"label": "主线焦点", "value": digest.get("main_focus") or "-", "hint": "只看有板块合力和核心地位的方向。"},
        {"label": "执行结论", "value": digest.get("execution") or "-", "hint": digest.get("tomorrow") or ""},
    ]
    metric_cards = "".join(
        f"""
        <section class="expert-metric-card">
          <small>{h(item.get('label'))}</small>
          <strong>{h(item.get('value'))}</strong>
          <span>{h(item.get('hint'))}</span>
        </section>
        """
        for item in metrics[:4]
    )
    decisions = digest.get("decisions") or [
        {"label": "共识", "text": digest.get("consensus") or "-"},
        {"label": "分歧", "text": digest.get("divergence") or "-"},
        {"label": "风险", "text": digest.get("risk") or "-"},
        {"label": "明日", "text": digest.get("tomorrow") or "-"},
    ]
    decision_rows = "".join(
        f'<div class="decision-row"><b>{h(item.get("label"))}</b><p>{h(item.get("text"))}</p></div>'
        for item in decisions
        if item.get("text")
    )
    briefs = digest.get("briefs") or [
        {"title": str(item).split("：", 1)[0], "text": str(item).split("：", 1)[1] if "：" in str(item) else str(item)}
        for item in (digest.get("filters") or [])
    ]
    brief_cards = "".join(
        f'<section class="brief-card"><strong>{h(item.get("title"))}</strong><span>{h(item.get("text"))}</span></section>'
        for item in briefs[:4]
    )
    heat_rows = "".join(
        f"""
        <div class="bar-line">
          <span>{h(item.get('label'))}</span>
          <div class="track"><div class="fill" style="width: {heat_width(str(item.get('level') or ''))}%;"></div></div>
          <b>{h(item.get('level'))}</b>
        </div>
        """
        for item in (digest.get("theme_heat") or [])
    )
    opportunities = "".join(f"<li>{h(item)}</li>" for item in (digest.get("opportunities") or []))
    risk_lines = "".join(f"<li>{h(item)}</li>" for item in (digest.get("risk_lines") or []))
    return f"""
    <div class="expert-digest">
      <b>跟踪对象发言精炼</b>
      <div class="expert-metrics">{metric_cards}</div>
      <div class="expert-summary-grid">
        <section class="expert-panel decision-panel">
          <h3>核心判断</h3>
          {decision_rows}
        </section>
        <section class="expert-panel">
          <h3>明日过滤器</h3>
          <div class="brief-grid">{brief_cards}</div>
        </section>
      </div>
      <div class="expert-wide-grid">
        <section class="expert-panel">
          <h3>主线热度</h3>
          <div class="bars">{heat_rows}</div>
        </section>
        <section class="expert-panel">
          <h3>机会线索</h3>
          <ul class="signal-list">{opportunities}</ul>
        </section>
        <section class="expert-panel">
          <h3>风险线索</h3>
          <ul class="signal-list">{risk_lines}</ul>
        </section>
      </div>
    </div>
    """


def render_dashboard_expert_quotes(digest: dict[str, Any]) -> str:
    if not digest or not digest.get("quotes"):
        return ""
    return f"""
    <section class="expert-quotes-panel panel">
      <strong class="subhead">有用摘录</strong>
      <p class="quote-rule">{h(digest.get('selection_rule') or '')}</p>
      <div class="quote-grid">{render_expert_quote_cards(digest)}</div>
    </section>
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
                "title": f"红色路径：收回5m中枢 {price(zd)}，再看上沿 {price(zg)}",
                "items": [
                    "这是下方离开失败后的回中枢，先按修复看。",
                    "继续站上中枢上沿后，才观察是否形成5m三买。",
                    "未完成中枢回收前，不把反抽当趋势买点。",
                ],
            },
            "yellow": {
                "title": f"黄色路径：守住近端底分型 {support_label}",
                "items": [
                    "只按弱修复处理，不把反弹当反转。",
                    "等待5m二买或重新回中枢确认。",
                    "未收回中枢下沿前，个股新增信号降级。",
                ],
            },
            "blue": {
                "title": f"蓝色路径：跌破近端底分型 {price(near_support)}",
                "items": [
                    "下方离开中枢延续，全部新增信号降级。",
                    "不新增趋势仓，先看是否出现背驰和止跌结构。",
                    "优先控制回撤，等待重新站回近端结构。",
                ],
            },
        }
    if close is not None and zd is not None and zg is not None and close <= zg:
        return {
            "red": {
                "title": f"红色路径：站上5m中枢上沿 {price(zg)}",
                "items": ["向上离开中枢，系统风险降级。", "回踩不破上沿才按5m三买确认。", "确认前不追VWAP正偏离急拉。"],
            },
            "yellow": {
                "title": f"黄色路径：中枢内守住 {price(zd)}",
                "items": ["仍是5m中枢震荡，只做承接验证。", "等待5m二买/三买，不开盘追价。", "中枢内个股等待方向选择。"],
            },
            "blue": {
                "title": f"蓝色路径：跌破5m中枢下沿 {price(zd)}",
                "items": ["向下离开中枢，全部新增信号降级。", "不新增趋势仓。", "先等背驰或重新回中枢确认。"],
            },
        }
    if close is not None and zg is not None and close > zg:
        day = index.get("day") or {}
        state30 = index.get("state_30m") or {}
        proj30 = index.get("projection_30m") or {}
        th30 = proj30.get("thresholds") or {}
        post10_low = safe_float(day.get("post10_low"))
        first30_close = safe_float(day.get("first30_close"))
        repair_gate = safe_float(th.get("next_close_for_dif_above_last_bottom")) or first30_close or close
        macd_gate = macd_floor or post10_low or close
        inner_hold = max(x for x in [post10_low, macd_gate] if x is not None)
        higher_repair = safe_float(th.get("next_close_for_dif_above_prev_bottom"))
        thirty_zg = safe_float(proj30.get("zg"))
        thirty_macd = safe_float(th30.get("flat_close_for_macd_improve"))
        red_target = higher_repair or thirty_macd or safe_float(day.get("high")) or close
        yellow_label = (
            f"{price(inner_hold)}-{price(repair_gate)}"
            if inner_hold is not None and repair_gate is not None and abs(inner_hold - repair_gate) > 0.01
            else price(inner_hold or repair_gate)
        )
        blue_first = thirty_zg or zg
        return {
            "red": {
                "title": f"红色路径：站稳离开段 {price(repair_gate)}，再看 {price(red_target)}",
                "items": [
                    "不是守老中枢，而是确认向上离开段继续有效。",
                    "5m DIF修复后，回踩不破离开段承接才算强结构延续。",
                    "确认前不追正偏离急拉，只做核心方向。"
                ],
            },
            "yellow": {
                "title": f"黄色路径：回踩离开段承接 {yellow_label}",
                "items": [
                    "这是离开段内部承接验证，不是回踩老中枢上沿。",
                    "守住后再看5m二买/三买；破掉则先降到震荡修复。",
                    "个股只看核心回踩承接，不追后排扩散。"
                ],
            },
            "blue": {
                "title": f"蓝色路径：跌回30m/5m防线 {price(blue_first)}，再看 {price(zg)}",
                "items": [
                    "跌回30m中枢上沿附近，说明离开段承接失败。",
                    f"{price(zg)} 是上一5m中枢上沿，只作为最后降级线，不是第一观察位。",
                    "跌回老中枢内则新增信号降级，等待重新构造。"
                ],
            },
        }
    return {
        "red": {
            "title": f"红色路径：回踩不破5m中枢上沿 {price(zg)}",
            "items": ["向上离开中枢后首次回踩不破，才算5m三买确认。", "只激活强结构个股。", "不追VWAP正偏离过大的急拉。"],
        },
        "yellow": {
            "title": f"黄色路径：回踩5m中枢上沿 {price(zg)}",
            "items": ["这是三买验证区，不是追价区。", "等待5m承接和低级别买点。", "跌回中枢内则降低新增优先级。"],
        },
        "blue": {
            "title": f"蓝色路径：跌回5m中枢内并失守 {price(zd)}",
            "items": ["向上离开失败，新增信号降级。", "不新增趋势仓。", "优先控制回撤，等待背驰或重新回中枢。"],
        },
    }


def compact_action_path_html(action_paths: dict[str, dict[str, Any]]) -> str:
    cards = []
    for key, label in [("red", "红"), ("yellow", "黄"), ("blue", "蓝")]:
        path = action_paths.get(key) or {}
        title = str(path.get("title") or "").replace("红色路径：", "").replace("黄色路径：", "").replace("蓝色路径：", "")
        summary = "；".join(str(item) for item in (path.get("items") or [])[:2])
        cards.append(
            f"""
            <div class="path-mini gate-{key}">
              <strong>{h(label)}：{h(title)}</strong>
              <span>{h(summary)}</span>
            </div>
            """
        )
    return "".join(cards)


def render_dashboard_market_overview(
    index: dict[str, Any],
    index_gate: str,
    ecology: dict[str, Any],
    action_paths: dict[str, dict[str, Any]],
    judgment: dict[str, Any] | None = None,
) -> str:
    judgment = judgment or {}
    center = index.get("geometry_5m", {}).get("center")
    day = index.get("day") or {}
    state30 = index.get("state_30m") or {}
    close = safe_float(day.get("close"))
    pos = center_position(close, center)
    dif = safe_float(state30.get("dif"))
    slope = safe_float(state30.get("dif_slope_12"))
    slope_text = "修复" if slope is not None and slope > 0 else "走弱"
    zd = safe_float((center or {}).get("ZD"))
    zg = safe_float((center or {}).get("ZG"))
    gate_text = {
        "red": "可观察强结构延续，但不追VWAP正偏离急拉。",
        "yellow": "只做承接验证，等5m二买/三买或回踩确认。",
        "blue": "新增买点降级，先防守，等指数重新收回近端结构。",
    }.get(index_gate, "先看指数中枢位置和承接质量。")
    if judgment and judgment.get("summary"):
        gate_text = str(judgment.get("summary"))
    if judgment and judgment.get("structure"):
        structure_text = str(judgment.get("structure"))
    elif close is not None and zd is not None and zg is not None and close < zd:
        structure_text = f"上证收 {price(close)}，落在5m{pos}，先看能否收回 {price(zd)}；收不回就仍是弱修复。30m DIF {price(dif, 3)}，斜率{slope_text}，不按反转处理。"
    elif close is not None and zg is not None and close > zg:
        red_title = str((action_paths.get("red") or {}).get("title") or "").replace("红色路径：", "")
        yellow_title = str((action_paths.get("yellow") or {}).get("title") or "").replace("黄色路径：", "")
        blue_title = str((action_paths.get("blue") or {}).get("title") or "").replace("蓝色路径：", "")
        structure_text = (
            f"上证收 {price(close)}，已处在向上离开段里；先看 {yellow_title}，"
            f"确认后再看 {red_title}。若转成 {blue_title}，才说明这段离开失败。"
            f"30m DIF {price(dif, 3)}，斜率{slope_text}，第一观察点不再是老中枢上沿。"
        )
    elif zd is not None and zg is not None:
        structure_text = f"上证收 {price(close)}，落在5m{pos}；站上 {price(zg)} 才转强，跌破 {price(zd)} 转防守。30m DIF {price(dif, 3)}，斜率{slope_text}，先看承接质量。"
    else:
        structure_text = f"上证收 {price(close)}，落在5m{pos}；30m DIF {price(dif, 3)}，斜率{slope_text}。结构位不完整时，先按VWAP和承接质量观察。"
    gate_text = str(judgment.get("summary") or gate_text)
    structure_text = str(judgment.get("structure") or structure_text)
    return f"""
    <div class="market-overview">
      <b>大盘总体分析</b>
      <div class="overview-grid">
        <section>
          <strong>结论</strong>
          <span>{h(gate_text)}</span>
        </section>
        <section>
          <strong>结构</strong>
          <span>{h(structure_text)}</span>
        </section>
        <section class="wide">
          <strong>题材</strong>
          <span>{h(theme_summary_line(ecology))}</span>
        </section>
        <section class="wide">
          <strong>明日路径</strong>
          <div class="path-mini-grid">{compact_action_path_html(action_paths)}</div>
        </section>
      </div>
    </div>
    """


def render_stock_card(report: dict[str, Any], index_gate: str) -> str:
    pos = (report.get("position") or {})
    action, reason = classify_symbol(report, index_gate, pos)
    symbol = report["symbol"]
    name = pos.get("name") or symbol
    judgment = report.get("judgment") or {}
    exec_state = report.get("execution") or {}
    geo = report.get("geometry_5m") or {}
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
    takeaway = str(judgment.get("takeaway") or "").strip() or takeaway
    summary_text = str(judgment.get("summary") or dashboard_stock_summary_text(report, action))
    structure_text = str(judgment.get("structure") or dashboard_stock_structure_text(report))
    theme_plan_text = str(judgment.get("theme_plan") or dashboard_stock_theme_plan_text(report, index_gate, pos, reason))
    badge_text = str(judgment.get("action_label") or action_label(action))
    title = f"{symbol} {name}" if name != symbol else symbol
    return f"""
    <article class="stock-card {css_class_for_action(action)}">
      <div class="card-head">
        <div>
          <h3>{h(title)}</h3>
        </div>
        <span class="action-badge">{h(badge_text)}</span>
      </div>
      <div class="takeaway">{h(takeaway)}</div>
      <div class="levels">{render_level_pills(report)}</div>
      <div class="stock-sections">
        <section>
          <b>结论</b>
          <span>{h(summary_text)}</span>
        </section>
        <section>
          <b>结构</b>
          <span>{h(structure_text)}</span>
        </section>
        <section>
          <b>题材与执行</b>
          <span>{h(theme_plan_text)}</span>
        </section>
      </div>
    </article>
    """


def render_dashboard_html(data: dict[str, Any]) -> str:
    index = data["index"]
    stocks = data["stocks"]
    index_gate = gate_state(index["current"])
    positions = data.get("positions") or {}
    market_ecology = data.get("market_ecology") or {}
    index_judgment = data.get("index_judgment") or {}
    index["judgment"] = index_judgment
    action_paths = final_index_action_paths(index, index_judgment)
    stock_judgments = data.get("stock_judgments") or {}
    theme_by_symbol = {
        normalize_symbol(str(row.get("code"))): row
        for row in (market_ecology.get("focus_stocks") or [])
        if row.get("code")
    }
    for report in stocks:
        report["position"] = positions.get(report["symbol"]) or {}
        report["theme_attribution"] = theme_by_symbol.get(report["symbol"]) or {}
        report["judgment"] = stock_judgments.get(report["symbol"]) or {}
    ranked = sorted(stocks, key=lambda r: action_rank(classify_symbol(r, index_gate, r.get("position") or {})[0]))

    market_overview_html = render_dashboard_market_overview(index, index_gate, market_ecology, action_paths, index_judgment)
    market_ecology_html = render_dashboard_market_ecology(market_ecology)
    expert_digest_html = render_dashboard_expert_digest(data.get("expert_digest") or {})
    expert_quotes_html = render_dashboard_expert_quotes(data.get("expert_digest") or {})

    stock_cards = "\n".join(render_stock_card(report, index_gate) for report in ranked)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{h(data['date'])} 复盘看板</title>
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
    .market-review-module {{ margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #fbfdff; }}
    .module-title {{ display: flex; justify-content: space-between; gap: 12px; align-items: baseline; margin-bottom: 8px; }}
    .module-title b {{ font-size: 16px; }}
    .module-title span {{ color: var(--muted); font-size: 13px; }}
    .market-overview {{ padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #ffffff; }}
    .market-overview b {{ display: block; margin-bottom: 5px; font-size: 14px; }}
    .overview-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 8px; }}
    .overview-grid section {{ border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #ffffff; }}
    .overview-grid section.wide {{ grid-column: span 2; }}
    .overview-grid strong {{ display: block; font-size: 13px; margin-bottom: 4px; }}
    .overview-grid span {{ display: block; color: #344054; font-size: 13px; }}
    .path-mini-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    .path-mini {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px; }}
    .path-mini strong {{ margin-bottom: 3px; }}
    .path-mini span {{ color: #344054; font-size: 12px; }}
    .market-ecology {{ margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #ffffff; }}
    .market-ecology b {{ display: block; margin-bottom: 8px; font-size: 14px; }}
    .market-ecology p {{ margin: 8px 0; color: #344054; font-size: 13px; }}
    .breadth-grid, .theme-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }}
    .breadth-grid span, .theme-chip {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: #f8fafc; }}
    .theme-chip strong {{ display: block; font-size: 13px; }}
    .theme-chip span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .theme-leaders {{ color: #344054 !important; }}
    .subhead {{ display: block; margin: 10px 0 6px; font-size: 13px; }}
    .strong-theme {{ background: #f0fdf4; border-color: #b7e4c7; }}
    .secondary-theme-grid .theme-chip {{ background: #fbfdff; }}
    .secondary-theme-grid .theme-chip strong {{ color: #475467; }}
    .expert-digest {{ margin-top: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: #ffffff; }}
    .expert-digest > b {{ display: block; margin-bottom: 8px; font-size: 14px; }}
    .expert-metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .expert-metric-card, .expert-panel, .quote-card {{ border: 1px solid var(--line); border-radius: 8px; background: #ffffff; box-shadow: var(--shadow); }}
    .expert-metric-card {{ padding: 12px; min-height: 94px; }}
    .expert-metric-card small {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 6px; }}
    .expert-metric-card strong {{ display: block; font-size: 20px; line-height: 1.25; margin-bottom: 5px; }}
    .expert-metric-card span {{ color: #667085; font-size: 13px; }}
    .expert-summary-grid {{ display: grid; grid-template-columns: 1.35fr 1fr; gap: 12px; margin-bottom: 12px; }}
    .expert-wide-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin-bottom: 12px; }}
    .expert-panel {{ padding: 14px; }}
    .expert-panel h3 {{ margin: 0 0 10px; font-size: 16px; }}
    .decision-row {{ display: grid; grid-template-columns: 70px 1fr; gap: 12px; padding: 9px 0; border-top: 1px solid #edf0f5; }}
    .decision-row:first-of-type {{ border-top: 0; padding-top: 0; }}
    .decision-row b {{ font-size: 13px; }}
    .decision-row p {{ margin: 0; color: #344054; font-size: 14px; }}
    .brief-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
    .brief-card {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }}
    .brief-card strong {{ display: block; margin-bottom: 5px; font-size: 13px; }}
    .brief-card span {{ color: #344054; font-size: 13px; }}
    .bars {{ display: grid; gap: 10px; }}
    .bar-line {{ display: grid; grid-template-columns: 78px 1fr 36px; gap: 8px; align-items: center; font-size: 13px; }}
    .track {{ height: 9px; border-radius: 999px; background: #edf0f5; overflow: hidden; }}
    .fill {{ height: 100%; border-radius: inherit; background: #2563eb; }}
    .signal-list {{ display: grid; gap: 8px; margin: 0; padding-left: 0; list-style: none; }}
    .signal-list li {{ position: relative; padding-left: 16px; color: #344054; font-size: 14px; }}
    .signal-list li::before {{ content: ""; position: absolute; left: 0; top: .72em; width: 6px; height: 6px; border-radius: 50%; background: #2563eb; }}
    .quote-rule {{ margin: -2px 0 8px; color: var(--muted); font-size: 13px; }}
    .expert-quotes-panel {{ margin: 16px 0; }}
    .expert-quotes-panel .subhead {{ font-size: 16px; margin-top: 0; }}
    .quote-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .quote-card {{ padding: 12px; display: flex; flex-direction: column; gap: 8px; background: #fbfcfe; }}
    .quote-meta {{ display: flex; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 12px; margin-bottom: 2px; }}
    .quote-meta span {{ color: #1f4e79; font-weight: 800; }}
    .quote-card blockquote {{ margin: 0; padding-left: 10px; border-left: 3px solid #bfd7fb; font-weight: 800; color: #17202a; }}
    .quote-card p {{ margin: 0; padding-top: 7px; border-top: 1px solid #edf0f5; color: #344054; font-size: 13px; }}
    .quote-card p b {{ color: #17202a; }}
    .quote-card a {{ margin-top: auto; color: #245985; font-size: 13px; font-weight: 800; text-decoration: none; }}
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
      .cards, .tree, .overview-grid, .path-mini-grid, .expert-metrics, .expert-summary-grid, .expert-wide-grid, .brief-grid, .quote-grid {{ grid-template-columns: 1fr; }}
      .overview-grid section.wide {{ grid-column: auto; }}
      .decision-row {{ grid-template-columns: 1fr; gap: 4px; }}
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
        <h1>{h(data['date'])} 复盘看板</h1>
        <section class="market-review-module">
          <div class="module-title">
            <b>盘面与题材复盘</b>
            <span>结构、全市场题材、跟踪对象判断合并阅读。</span>
          </div>
          {market_overview_html}
          {market_ecology_html}
          {expert_digest_html}
        </section>
      </div>
    </section>

    {expert_quotes_html}

    <h2 class="section-title">标的复盘</h2>
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


def load_daily_expert_digest(report_date: str, base_dir: Path) -> dict[str, Any]:
    date_slug = str(report_date).replace("-", "")
    path = base_dir / f"{date_slug}_expert_digest.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {}
    updated_at = str(data.get("updated_at") or data.get("date") or "")
    if updated_at and str(report_date) not in updated_at:
        return {}
    data.setdefault("source", str(path))
    return data


def load_daily_index_judgment(report_date: str, base_dir: Path) -> dict[str, Any]:
    date_slug = str(report_date).replace("-", "")
    path = base_dir / f"{date_slug}_index_judgment.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {}
    updated_at = str(data.get("updated_at") or data.get("date") or "")
    if updated_at and str(report_date) not in updated_at:
        return {}
    data.setdefault("source", str(path))
    return data


def load_daily_stock_judgments(report_date: str, base_dir: Path) -> dict[str, dict[str, Any]]:
    date_slug = str(report_date).replace("-", "")
    path = base_dir / f"{date_slug}_stock_judgments.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {}
    updated_at = str(data.get("updated_at") or data.get("date") or "")
    if updated_at and str(report_date) not in updated_at:
        return {}
    judgments = data.get("judgments") or {}
    result: dict[str, dict[str, Any]] = {}
    for symbol, item in judgments.items():
        if isinstance(item, dict):
            normalized = normalize_symbol(str(symbol))
            result[normalized] = dict(item)
            result[normalized].setdefault("source", str(path))
    return result


def normalize_action_paths(action_paths: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, label in [("red", "红色路径"), ("yellow", "黄色路径"), ("blue", "蓝色路径")]:
        item = (action_paths or {}).get(key) or {}
        title = str(item.get("title") or "").strip()
        if title and "路径：" not in title:
            title = f"{label}：{title}"
        result[key] = {
            "title": title or f"{label}：待判断",
            "items": [str(x) for x in (item.get("items") or []) if str(x).strip()],
        }
    return result


def final_index_action_paths(index: dict[str, Any], judgment: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    if judgment and isinstance(judgment.get("paths"), dict):
        return normalize_action_paths(judgment.get("paths"))
    return index_action_paths(index)


def write_daily_review_html(report_date: str, html: str, base_dir: Path = DAILY_REVIEW_DIR) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    date_slug = str(report_date).replace("-", "")
    path = base_dir / f"{date_slug}_每日复盘.html"
    path.write_text(html, encoding="utf-8-sig")
    return path


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


def config_market_context(config: dict[str, Any], report_date: str) -> dict[str, Any]:
    context = config.get("market_context", {}) or {}
    date_hint = " ".join(str(context.get(key) or "") for key in ["date", "updated_at", "as_of"])
    if date_hint and str(report_date) in date_hint:
        return context
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chanlun four-layer replay and next-day action tree.")
    parser.add_argument("--index", default=DEFAULT_INDEX, help="Index symbol, default sh000001.")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="Stock symbols.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Optional watchlist/position JSON config.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory.")
    parser.add_argument("--daily-review-dir", type=Path, default=DAILY_REVIEW_DIR, help="Cloud reading HTML output directory.")

    parser.add_argument("--json", action="store_true", help="Also print compact JSON to stdout.")
    args = parser.parse_args()

    config = load_config(args.config)
    index = config.get("index", args.index)
    symbols = config_symbols(config) if config else args.symbols
    if not symbols:
        symbols = args.symbols
    if not symbols:
        parser.error("No replay symbols configured. Update watchlist_config.json or pass --symbols.")
    data = build_data(index, symbols)
    positions = config_positions(config)
    data["config_path"] = str(args.config) if args.config else None
    data["positions"] = positions
    data["account"] = config.get("account", {})
    data["market_context"] = config_market_context(config, data["date"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    date_slug = str(data["date"]).replace("-", "")
    curated_digest = load_daily_expert_digest(data["date"], args.out_dir)
    data["index_judgment"] = load_daily_index_judgment(data["date"], args.out_dir)
    data["stock_judgments"] = load_daily_stock_judgments(data["date"], args.out_dir)
    data["expert_digest"] = merged_expert_digest(config.get("expert_digest", {}), data["date"], curated_digest)
    focus_symbols = sorted(set(symbols) | set(positions.keys()))
    data["market_ecology"] = build_market_ecology(data["date"], focus_symbols)
    md_path = args.out_dir / f"{date_slug}_chanlun_replay_plan.md"
    json_path = args.out_dir / f"{date_slug}_chanlun_replay_plan.json"
    html_path = args.out_dir / f"{date_slug}_chanlun_dashboard.html"
    html_content = render_dashboard_html(data)
    md_path.write_text(render_report(data), encoding="utf-8-sig")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(html_content, encoding="utf-8-sig")
    daily_review_path = write_daily_review_html(data["date"], html_content, args.daily_review_dir)


    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    print(f"wrote {html_path}")
    print(f"wrote {daily_review_path}")
    if args.json:
        print(json.dumps({"markdown": str(md_path), "json": str(json_path), "html": str(html_path), "daily_review_html": str(daily_review_path), "date": data["date"]}, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
