from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


QUANTUM_BUFFER = 0.0005
MOMENTUM_THRESHOLD = 0.7
DIF_PEAK_THRESHOLD = 0.95
STRUCTURE_WEAK_PUSH_MAX = 1.35
STRONG_PRIMARY_THRESHOLD = 0.60


@dataclass(frozen=True)
class OriginalSignal:
    date: pd.Timestamp
    value: float
    label: str
    kind: str
    evidence: dict[str, Any]


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "time" not in df.columns and "day" in df.columns:
        df = df.rename(columns={"day": "time"})
    required = ["time", "open", "high", "low", "close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" in df.columns:
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0)
    return df.dropna(subset=required)


def add_macd(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["EMA26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["DIF"] = df["EMA12"] - df["EMA26"]
    df["DEA"] = df["DIF"].ewm(span=9, adjust=False).mean()
    df["MACD"] = (df["DIF"] - df["DEA"]) * 2
    return df


def macd_momentum(df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp, direction_val: int) -> float:
    mask = (df["time"] >= start_date) & (df["time"] <= end_date)
    sub = df.loc[mask, "MACD"]
    if direction_val == 1:
        res = sub[sub > 0].sum()
        return float(res if res > 0.0001 else 0.0001)
    res = sub[sub < 0].sum()
    return float(abs(res) if res < -0.0001 else 0.0001)


def dif_peak(df: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp, direction_val: int) -> float:
    mask = (df["time"] >= start_date) & (df["time"] <= end_date)
    sub = df.loc[mask, "DIF"]
    if sub.empty:
        return 0.0001
    if direction_val == 1:
        val = float(sub.max())
        return val if val > 0.0001 else 0.0001
    val = float(abs(sub.min()))
    return val if val > 0.0001 else 0.0001


def compute_chanlun_original(data_df: pd.DataFrame) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    merged_k: list[dict] = []
    direction = 1
    for i in range(len(data_df)):
        row = data_df.iloc[i]
        current = {
            "date": row["time"],
            "high": float(row["high"]),
            "low": float(row["low"]),
            "open": float(row["open"]),
            "close": float(row["close"]),
        }
        if len(merged_k) < 2:
            merged_k.append(current)
            continue
        prev = merged_k[-1]
        prev2 = merged_k[-2]
        if prev["high"] > prev2["high"] and prev["low"] > prev2["low"]:
            direction = 1
        elif prev["high"] < prev2["high"] and prev["low"] < prev2["low"]:
            direction = -1

        inclusive = (
            current["high"] <= prev["high"] and current["low"] >= prev["low"]
        ) or (
            current["high"] >= prev["high"] and current["low"] <= prev["low"]
        )
        if inclusive:
            if direction == 1:
                merged_k[-1]["high"] = max(current["high"], prev["high"])
                merged_k[-1]["low"] = max(current["low"], prev["low"])
            else:
                merged_k[-1]["high"] = min(current["high"], prev["high"])
                merged_k[-1]["low"] = min(current["low"], prev["low"])
            merged_k[-1]["date"] = current["date"]
        else:
            merged_k.append(current)
    merged_df = pd.DataFrame(merged_k)

    fractals: list[dict] = []
    for i in range(1, len(merged_df) - 1):
        prev = merged_df.iloc[i - 1]
        curr = merged_df.iloc[i]
        next_k = merged_df.iloc[i + 1]
        if (
            curr["high"] > prev["high"]
            and curr["high"] > next_k["high"]
            and curr["low"] > prev["low"]
            and curr["low"] > next_k["low"]
        ):
            fractals.append({"type": "Top", "date": curr["date"], "val": float(curr["high"]), "index": i})
        if (
            curr["low"] < prev["low"]
            and curr["low"] < next_k["low"]
            and curr["high"] < prev["high"]
            and curr["high"] < next_k["high"]
        ):
            fractals.append({"type": "Bottom", "date": curr["date"], "val": float(curr["low"]), "index": i})

    valid_fractals: list[dict] = []
    if fractals:
        current_f = fractals[0]
        valid_fractals = [current_f]
        for f in fractals[1:]:
            if f["type"] != current_f["type"] and (f["index"] - current_f["index"]) >= 4:
                valid_fractals.append(f)
                current_f = f
            elif f["type"] == current_f["type"]:
                if f["type"] == "Top" and f["val"] > current_f["val"]:
                    valid_fractals[-1] = f
                    current_f = f
                elif f["type"] == "Bottom" and f["val"] < current_f["val"]:
                    valid_fractals[-1] = f
                    current_f = f

    cleaned_zs: list[dict] = []
    i = 0
    while i < len(valid_fractals) - 3:
        f1, f2, f3, f4 = valid_fractals[i], valid_fractals[i + 1], valid_fractals[i + 2], valid_fractals[i + 3]
        highs = [f["val"] for f in [f1, f2, f3, f4] if f["type"] == "Top"]
        lows = [f["val"] for f in [f1, f2, f3, f4] if f["type"] == "Bottom"]
        if len(highs) == 2 and len(lows) == 2:
            zg = min(highs)
            zd = max(lows)
            if zg >= zd:
                curr_zs = {"ZG": zg, "ZD": zd, "start": min(f2["date"], f3["date"]), "end": f4["date"]}
                j = i + 3
                stroke_count = 3
                while j < len(valid_fractals) - 1:
                    current_f, next_f = valid_fractals[j], valid_fractals[j + 1]
                    stroke_high = max(current_f["val"], next_f["val"])
                    stroke_low = min(current_f["val"], next_f["val"])
                    if stroke_low <= curr_zs["ZG"] and stroke_high >= curr_zs["ZD"]:
                        if stroke_count >= 9:
                            break
                        curr_zs["end"] = next_f["date"]
                        stroke_count += 1
                        j += 1
                    else:
                        break
                cleaned_zs.append(curr_zs)
                i = j
                continue
        i += 1

    raw_bs_points: list[dict] = []
    traps: list[dict] = []

    def previous_center(current_zs: dict) -> dict | None:
        for idx, item in enumerate(cleaned_zs):
            if item is current_zs:
                return cleaned_zs[idx - 1] if idx > 0 else None
        return None

    def has_downtrend_context(current_zs: dict) -> bool:
        prior = previous_center(current_zs)
        return bool(prior and current_zs["ZG"] < prior["ZG"] and current_zs["ZD"] < prior["ZD"])

    def has_uptrend_context(current_zs: dict) -> bool:
        prior = previous_center(current_zs)
        return bool(prior and current_zs["ZG"] > prior["ZG"] and current_zs["ZD"] > prior["ZD"])

    for i in range(4, len(valid_fractals)):
        f_curr = valid_fractals[i]
        applicable_zs = [z for z in cleaned_zs if z["start"] < f_curr["date"]]

        if f_curr["type"] == "Bottom":
            f_prev_bot = valid_fractals[i - 2]
            if f_curr["val"] < f_prev_bot["val"]:
                if f_curr["val"] >= f_prev_bot["val"] * (1 - QUANTUM_BUFFER):
                    traps.append({"date": f_curr["date"], "val": f_curr["val"], "label": "诱空", "type": "Bottom"})
                elif applicable_zs:
                    recent_z = applicable_zs[-1]
                    if not has_downtrend_context(recent_z):
                        continue
                    touch_fractals = [
                        f
                        for f in valid_fractals
                        if recent_z["start"] <= f["date"] < f_curr["date"]
                        and recent_z["ZD"] <= f["val"] <= recent_z["ZG"]
                    ]
                    hub_exit_date = touch_fractals[-1]["date"] if touch_fractals else recent_z["start"]
                    mom_b = macd_momentum(data_df, hub_exit_date, f_curr["date"], -1)
                    entry_fracs = [f for f in valid_fractals if f["date"] < recent_z["start"]]
                    if entry_fracs:
                        prev_tops = [f for f in entry_fracs if f["type"] == "Top"]
                        start_a = prev_tops[-1]["date"] if prev_tops else entry_fracs[-1]["date"]
                    else:
                        start_a = valid_fractals[0]["date"]
                    mom_a = macd_momentum(data_df, start_a, recent_z["start"], -1)
                    dif_b = dif_peak(data_df, hub_exit_date, f_curr["date"], -1)
                    dif_a = dif_peak(data_df, start_a, recent_z["start"], -1)
                    inter_tops = [
                        f for f in valid_fractals if f["type"] == "Top" and f_prev_bot["date"] < f["date"] < f_curr["date"]
                    ]
                    structure_ok = True
                    weak_drop_ratio = None
                    if inter_tops:
                        local_high = max(inter_tops, key=lambda x: x["val"])
                        den = max(1e-6, float(local_high["val"]) - float(f_prev_bot["val"]))
                        weak_drop_ratio = (float(local_high["val"]) - float(f_curr["val"])) / den
                        structure_ok = weak_drop_ratio <= STRUCTURE_WEAK_PUSH_MAX
                    primary_ok = mom_b < mom_a * MOMENTUM_THRESHOLD
                    secondary_ok = dif_b < dif_a * DIF_PEAK_THRESHOLD and structure_ok
                    strong_primary_ok = mom_b < mom_a * STRONG_PRIMARY_THRESHOLD
                    if primary_ok and (secondary_ok or strong_primary_ok):
                        raw_bs_points.append(
                            {
                                "date": f_curr["date"],
                                "val": f_curr["val"],
                                "label": "1B",
                                "type": "Bottom",
                                "evidence": {
                                    "zs": recent_z,
                                    "macd_current_area": mom_b,
                                    "macd_previous_area": mom_a,
                                    "dif_current_peak": dif_b,
                                    "dif_previous_peak": dif_a,
                                    "structure_weak_drop_ratio": weak_drop_ratio,
                                    "primary_ok": primary_ok,
                                    "secondary_ok": secondary_ok,
                                    "strong_primary_ok": strong_primary_ok,
                                },
                            }
                        )
            elif f_curr["val"] > f_prev_bot["val"]:
                recent_1bs = [b for b in raw_bs_points if b["label"] == "1B" and b["date"] < f_curr["date"]]
                if recent_1bs:
                    last_1b = recent_1bs[-1]
                    opposite_after_1b = any(
                        b["label"] == "1S" and last_1b["date"] < b["date"] < f_curr["date"]
                        for b in raw_bs_points
                    )
                    second_already_exists = any(
                        b["label"] == "2B"
                        and b.get("evidence", {}).get("first_signal_time") == last_1b["date"]
                        for b in raw_bs_points
                    )
                    if opposite_after_1b or second_already_exists:
                        continue
                    if f_curr["val"] > last_1b["val"]:
                        post_1b_tops = [
                            f for f in valid_fractals if f["type"] == "Top" and last_1b["date"] < f["date"] < f_curr["date"]
                        ]
                        if post_1b_tops:
                            highest_top = max(post_1b_tops, key=lambda x: x["val"])
                            mom_build_up = macd_momentum(data_df, last_1b["date"], highest_top["date"], 1)
                            mom_pullback = macd_momentum(data_df, highest_top["date"], f_curr["date"], -1)
                            if mom_pullback < mom_build_up * 0.8:
                                raw_bs_points.append(
                                    {
                                        "date": f_curr["date"],
                                        "val": f_curr["val"],
                                        "label": "2B",
                                        "type": "Bottom",
                                        "evidence": {
                                            "first_signal_time": last_1b["date"],
                                            "first_signal_value": last_1b["val"],
                                            "macd_pullback_area": mom_pullback,
                                            "macd_build_area": mom_build_up,
                                        },
                                    }
                                )

        elif f_curr["type"] == "Top":
            f_prev_top = valid_fractals[i - 2]
            if f_curr["val"] > f_prev_top["val"]:
                if f_curr["val"] <= f_prev_top["val"] * (1 + QUANTUM_BUFFER):
                    traps.append({"date": f_curr["date"], "val": f_curr["val"], "label": "诱多", "type": "Top"})
                elif applicable_zs:
                    recent_z = applicable_zs[-1]
                    if not has_uptrend_context(recent_z):
                        continue
                    touch_fractals = [
                        f
                        for f in valid_fractals
                        if recent_z["start"] <= f["date"] < f_curr["date"]
                        and recent_z["ZD"] <= f["val"] <= recent_z["ZG"]
                    ]
                    hub_exit_date = touch_fractals[-1]["date"] if touch_fractals else recent_z["start"]
                    mom_b = macd_momentum(data_df, hub_exit_date, f_curr["date"], 1)
                    entry_fracs = [f for f in valid_fractals if f["date"] < recent_z["start"]]
                    if entry_fracs:
                        prev_bots = [f for f in entry_fracs if f["type"] == "Bottom"]
                        start_a = prev_bots[-1]["date"] if prev_bots else entry_fracs[-1]["date"]
                    else:
                        start_a = valid_fractals[0]["date"]
                    mom_a = macd_momentum(data_df, start_a, recent_z["start"], 1)
                    dif_b = dif_peak(data_df, hub_exit_date, f_curr["date"], 1)
                    dif_a = dif_peak(data_df, start_a, recent_z["start"], 1)
                    inter_bots = [
                        f for f in valid_fractals if f["type"] == "Bottom" and f_prev_top["date"] < f["date"] < f_curr["date"]
                    ]
                    structure_ok = True
                    weak_push_ratio = None
                    if inter_bots:
                        local_low = min(inter_bots, key=lambda x: x["val"])
                        den = max(1e-6, float(f_prev_top["val"]) - float(local_low["val"]))
                        weak_push_ratio = (float(f_curr["val"]) - float(local_low["val"])) / den
                        structure_ok = weak_push_ratio <= STRUCTURE_WEAK_PUSH_MAX
                    primary_ok = mom_b < mom_a * MOMENTUM_THRESHOLD
                    secondary_ok = dif_b < dif_a * DIF_PEAK_THRESHOLD and structure_ok
                    strong_primary_ok = mom_b < mom_a * STRONG_PRIMARY_THRESHOLD
                    if primary_ok and (secondary_ok or strong_primary_ok):
                        raw_bs_points.append(
                            {
                                "date": f_curr["date"],
                                "val": f_curr["val"],
                                "label": "1S",
                                "type": "Top",
                                "evidence": {
                                    "zs": recent_z,
                                    "macd_current_area": mom_b,
                                    "macd_previous_area": mom_a,
                                    "dif_current_peak": dif_b,
                                    "dif_previous_peak": dif_a,
                                    "structure_weak_push_ratio": weak_push_ratio,
                                    "primary_ok": primary_ok,
                                    "secondary_ok": secondary_ok,
                                    "strong_primary_ok": strong_primary_ok,
                                },
                            }
                        )
            elif f_curr["val"] < f_prev_top["val"]:
                recent_1ss = [b for b in raw_bs_points if b["label"] == "1S" and b["date"] < f_curr["date"]]
                if recent_1ss:
                    last_1s = recent_1ss[-1]
                    opposite_after_1s = any(
                        b["label"] == "1B" and last_1s["date"] < b["date"] < f_curr["date"]
                        for b in raw_bs_points
                    )
                    second_already_exists = any(
                        b["label"] == "2S"
                        and b.get("evidence", {}).get("first_signal_time") == last_1s["date"]
                        for b in raw_bs_points
                    )
                    if opposite_after_1s or second_already_exists:
                        continue
                    if f_curr["val"] < last_1s["val"]:
                        post_1s_bots = [
                            f for f in valid_fractals if f["type"] == "Bottom" and last_1s["date"] < f["date"] < f_curr["date"]
                        ]
                        if post_1s_bots:
                            lowest_bot = min(post_1s_bots, key=lambda x: x["val"])
                            mom_crash_down = macd_momentum(data_df, last_1s["date"], lowest_bot["date"], -1)
                            mom_rebound_up = macd_momentum(data_df, lowest_bot["date"], f_curr["date"], 1)
                            if mom_rebound_up < mom_crash_down * 0.8:
                                raw_bs_points.append(
                                    {
                                        "date": f_curr["date"],
                                        "val": f_curr["val"],
                                        "label": "2S",
                                        "type": "Top",
                                        "evidence": {
                                            "first_signal_time": last_1s["date"],
                                            "first_signal_value": last_1s["val"],
                                            "macd_rebound_area": mom_rebound_up,
                                            "macd_crash_area": mom_crash_down,
                                        },
                                    }
                                )

    bs_points: list[dict] = []
    raw_bs_points = sorted(raw_bs_points, key=lambda x: x["date"])
    for bp in raw_bs_points:
        if not bs_points:
            bs_points.append(bp)
            continue
        prev_bp = bs_points[-1]
        if bp["label"] == "1B" and prev_bp["label"] == "1B":
            if bp["val"] <= prev_bp["val"]:
                bs_points[-1] = bp
        elif bp["label"] == "1S" and prev_bp["label"] == "1S":
            if bp["val"] >= prev_bp["val"]:
                bs_points[-1] = bp
        elif bp["label"] == "2B" and prev_bp["label"] == "2B":
            if bp["val"] <= prev_bp["val"]:
                bs_points[-1] = bp
        elif bp["label"] == "2S" and prev_bp["label"] == "2S":
            if bp["val"] >= prev_bp["val"]:
                bs_points[-1] = bp
        else:
            bs_points.append(bp)

    return valid_fractals, cleaned_zs, bs_points, traps


def add_level_3bs(zs_list: list[dict], frac_list: list[dict], target_bs_list: list[dict], data_df: pd.DataFrame) -> None:
    if not zs_list:
        return
    for idx, zs in enumerate(reversed(zs_list)):
        zg, zd = zs["ZG"], zs["ZD"]
        actual_idx = len(zs_list) - 1 - idx
        next_zs_start = zs_list[actual_idx + 1]["start"] if (actual_idx + 1 < len(zs_list)) else None
        post_fracs = [f for f in frac_list if f["date"] > zs["end"]]
        if next_zs_start:
            post_fracs = [f for f in post_fracs if f["date"] < next_zs_start]
        if not post_fracs:
            continue

        break_down = False
        last_bot = None
        for f in post_fracs:
            if f["type"] == "Bottom" and f["val"] < zd:
                break_down = True
                last_bot = f
            elif break_down and f["type"] == "Top":
                if f["val"] < zd and last_bot:
                    mom_rebound = macd_momentum(data_df, last_bot["date"], f["date"], 1)
                    mom_base_up = macd_momentum(data_df, zs["start"], zs["end"], 1)
                    if mom_rebound < mom_base_up * MOMENTUM_THRESHOLD:
                        if not any(b["date"] == f["date"] and "3S" in b["label"] for b in target_bs_list):
                            target_bs_list.append(
                                {
                                    "date": f["date"],
                                    "val": f["val"],
                                    "label": "3S",
                                    "type": "Top",
                                    "evidence": {
                                        "zs": zs,
                                        "boundary_name": "ZD",
                                        "boundary": zd,
                                        "leave_time": last_bot["date"],
                                        "macd_test_area": mom_rebound,
                                        "macd_base_area": mom_base_up,
                                    },
                                }
                            )
                        break
                else:
                    break_down = False

        break_up = False
        last_top = None
        for f in post_fracs:
            if f["type"] == "Top" and f["val"] > zg:
                break_up = True
                last_top = f
            elif break_up and f["type"] == "Bottom":
                if f["val"] > zg and last_top:
                    mom_pullback = macd_momentum(data_df, last_top["date"], f["date"], -1)
                    mom_base_down = macd_momentum(data_df, zs["start"], zs["end"], -1)
                    if mom_pullback < mom_base_down * MOMENTUM_THRESHOLD:
                        if not any(b["date"] == f["date"] and "3B" in b["label"] for b in target_bs_list):
                            target_bs_list.append(
                                {
                                    "date": f["date"],
                                    "val": f["val"],
                                    "label": "3B",
                                    "type": "Bottom",
                                    "evidence": {
                                        "zs": zs,
                                        "boundary_name": "ZG",
                                        "boundary": zg,
                                        "leave_time": last_top["date"],
                                        "macd_test_area": mom_pullback,
                                        "macd_base_area": mom_base_down,
                                    },
                                }
                            )
                        break
                else:
                    break_up = False
        break


def analyze_frame_original(df: pd.DataFrame, level: str) -> dict:
    data = add_macd(normalize_ohlc(df))
    data["dif"] = data["DIF"]
    data["dea"] = data["DEA"]
    data["macd"] = data["MACD"]
    fractals, zs, bs, traps = compute_chanlun_original(data)
    add_level_3bs(zs, fractals, bs, data)
    valid_dates = {f["date"] for f in fractals}
    bs = [b for b in bs if b["date"] in valid_dates]
    traps = [t for t in traps if t["date"] in valid_dates]
    bs = sorted(bs, key=lambda x: x["date"])
    bi_points = [{"time": f["date"], "value": f["val"]} for f in fractals]
    return {
        "df": data,
        "fractals": fractals,
        "zs": zs,
        "signals": bs,
        "traps": traps,
        "bi_points": bi_points,
        "level": level,
    }
