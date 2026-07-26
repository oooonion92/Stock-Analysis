from __future__ import annotations

import copy
import hashlib
import json
import sys
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CHANPY_COMMIT = "429d6ed3043e27c93a003ba2b10e70a05575e1f5"
WEAKENING_RATIO = 0.85
REQUIRED_MOMENTUM_VOTES = 2
VENDOR_ROOT = Path(__file__).resolve().parents[2] / "vendor" / "chanpy"

if str(VENDOR_ROOT) not in sys.path:
    sys.path.insert(0, str(VENDOR_ROOT))

from Chan import CChan  # noqa: E402
from ChanConfig import CChanConfig  # noqa: E402
from Common.CEnum import DATA_FIELD, KL_TYPE  # noqa: E402
from Common.CTime import CTime  # noqa: E402
from KLine.KLine_Unit import CKLine_Unit  # noqa: E402


LEVEL_MAP = {
    "5m": KL_TYPE.K_5M,
    "30m": KL_TYPE.K_30M,
    "1d": KL_TYPE.K_DAY,
}
PARENT_LEVEL = {"5m": "30m", "30m": "1d", "1d": "1w"}


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(raw).hexdigest()[:12]}"


def _iso(value: datetime | pd.Timestamp) -> str:
    return pd.Timestamp(value).isoformat()


def _ratio(test: float, reference: float) -> float | None:
    return None if reference == 0 else float(test) / float(reference)


def _safe_index(index: int, size: int) -> int:
    return max(0, min(int(index), size - 1))


class ChanPyEngine:
    """Adapter from pinned chan.py objects to the V2 response contract."""

    def __init__(self, cache_size: int = 18) -> None:
        self.cache_size = cache_size
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cache_lock = threading.RLock()

    def analyze(self, frame: pd.DataFrame, level: str, profile: dict[str, Any]) -> dict[str, Any]:
        if level not in LEVEL_MAP:
            raise ValueError(f"chan.py 暂不支持周期: {level}")
        data = self._with_macd(frame)
        key = self._cache_key(data, level, profile)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return copy.deepcopy(cached)

        config = CChanConfig(
            {
                "trigger_step": True,
                "kl_data_check": False,
                "print_warning": False,
                "print_err_time": False,
                "zs_combine": True,
                "zs_combine_mode": "zs",
            }
        )
        kl_type = LEVEL_MAP[level]
        chan = CChan("local", lv_list=[kl_type], config=config)
        chan.trigger_load({kl_type: self._build_units(data, kl_type)})
        source = chan[kl_type]

        strokes_native = list(source.bi_list)
        segments_native = list(source.seg_list)
        higher_segments_native = list(source.segseg_list)
        centers_native = list(source.zs_list)
        segment_centers_native = list(source.segzs_list)

        strokes = [self._line_record(item, data, level, "stroke") for item in strokes_native]
        segments = [self._line_record(item, data, level, "segment") for item in segments_native]
        higher_segments = [
            self._line_record(item, data, PARENT_LEVEL.get(level, f"{level}+"), "higher_segment")
            for item in higher_segments_native
        ]
        pivots = self._pivots(strokes_native, data, level, "stroke")
        segment_pivots = self._pivots(segments_native, data, level, "segment")
        centers = [self._center_record(item, data, level, "stroke") for item in centers_native]
        segment_centers = [
            self._center_record(item, data, PARENT_LEVEL.get(level, f"{level}+"), "segment")
            for item in segment_centers_native
        ]

        pen_active, pen_history = self._signals(
            source.bs_point_lst.bsp_iter(), False, strokes_native, segments_native, data, level
        )
        segment_active, segment_history = self._signals(
            source.seg_bs_point_lst.bsp_iter(), True, segments_native, higher_segments_native, data, level
        )
        signals = sorted([*pen_active, *segment_active], key=self._signal_sort_key)
        signal_history = sorted([*pen_history, *segment_history], key=self._signal_sort_key)
        current = self._current_state(data, centers, strokes, segments, signals)

        result = {
            "engine": "chan.py",
            "engine_commit": CHANPY_COMMIT,
            "level": level,
            "pivots": pivots,
            "strokes": strokes,
            "segment_pivots": segment_pivots,
            "segments": segments,
            "higher_segments": higher_segments,
            "centers": centers,
            "segment_centers": segment_centers,
            "promoted_centers": segment_centers,
            "inherited_centers": [],
            "promoted_signals": [],
            "signals": signals,
            "signal_history": signal_history,
            "current": current,
            "macd": {
                "dif": data["dif"].round(6).tolist(),
                "dea": data["dea"].round(6).tolist(),
                "histogram": data["macd"].round(6).tolist(),
            },
            "summary": {
                "bars": len(data),
                "pivots": len(pivots),
                "strokes": len(strokes),
                "confirmed_strokes": sum(bool(item["is_sure"]) for item in strokes),
                "segments": len(segments),
                "confirmed_segments": sum(bool(item["is_sure"]) for item in segments),
                "higher_segments": len(higher_segments),
                "centers": len(centers),
                "segment_centers": len(segment_centers),
                "signals": len(signals),
                "signal_history": len(signal_history),
                "strict_first_signals": sum(
                    item["evidence"].get("divergence_audit", {}).get("status") == "confirmed"
                    for item in signal_history
                ),
            },
        }
        with self._cache_lock:
            self._cache[key] = copy.deepcopy(result)
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return result

    @staticmethod
    def _with_macd(frame: pd.DataFrame) -> pd.DataFrame:
        data = frame.copy().reset_index(drop=True)
        ema12 = data["close"].ewm(span=12, adjust=False).mean()
        ema26 = data["close"].ewm(span=26, adjust=False).mean()
        data["dif"] = ema12 - ema26
        data["dea"] = data["dif"].ewm(span=9, adjust=False).mean()
        data["macd"] = (data["dif"] - data["dea"]) * 2
        return data

    @staticmethod
    def _cache_key(data: pd.DataFrame, level: str, profile: dict[str, Any]) -> str:
        columns = ["time", "open", "high", "low", "close", "volume", "amount"]
        digest = hashlib.sha256(pd.util.hash_pandas_object(data[columns], index=False).values.tobytes()).hexdigest()
        profile_key = json.dumps(profile, sort_keys=True, default=str)
        return f"{level}|{digest}|{profile_key}|{CHANPY_COMMIT}"

    @staticmethod
    def _build_units(data: pd.DataFrame, level: KL_TYPE) -> list[CKLine_Unit]:
        units: list[CKLine_Unit] = []
        for row in data.itertuples(index=False):
            current = pd.Timestamp(row.time)
            unit = CKLine_Unit(
                {
                    DATA_FIELD.FIELD_TIME: CTime(
                        current.year,
                        current.month,
                        current.day,
                        current.hour,
                        current.minute,
                        current.second,
                        auto=False,
                    ),
                    DATA_FIELD.FIELD_OPEN: float(row.open),
                    DATA_FIELD.FIELD_HIGH: float(row.high),
                    DATA_FIELD.FIELD_LOW: float(row.low),
                    DATA_FIELD.FIELD_CLOSE: float(row.close),
                    DATA_FIELD.FIELD_VOLUME: float(row.volume),
                    DATA_FIELD.FIELD_TURNOVER: float(row.amount),
                }
            )
            unit.kl_type = level
            units.append(unit)
        return units

    def _line_record(self, line: Any, data: pd.DataFrame, level: str, kind: str) -> dict[str, Any]:
        start = _safe_index(line.get_begin_klu().idx, len(data))
        end = _safe_index(line.get_end_klu().idx, len(data))
        if start > end:
            start, end = end, start
        metrics = self._line_metrics(line, data, "")
        confirmed_index = self._confirmation_index(line, len(data))
        record = {
            "id": _stable_id("chanpy-line", level, kind, start, end),
            "level": level,
            "start_at": _iso(data.iloc[start]["time"]),
            "end_at": _iso(data.iloc[end]["time"]),
            "confirmed_at": _iso(data.iloc[confirmed_index]["time"]),
            "direction": metrics["direction"],
            "start_price": metrics["startValue"],
            "end_price": metrics["endValue"],
            "stroke_count": int(line.cal_bi_cnt()) if hasattr(line, "cal_bi_cnt") else 1,
            "bars": metrics["bars"],
            "price_move": metrics["priceMove"],
            "macd_area": metrics["macdArea"],
            "macd_peak": metrics["macdPeak"],
            "dif_extreme": metrics["difExtreme"],
            "volume": metrics["volumeTotal"],
            "volume_average": metrics["volumeAverage"],
            "amount_average": metrics["amountAverage"],
            "is_sure": bool(line.is_sure if hasattr(line, "is_sure") and not callable(line.is_sure) else line.is_sure()),
            "source_kind": kind,
            "source_index": int(line.idx),
        }
        if hasattr(line, "reason"):
            record["reason"] = line.reason
        return record

    def _pivots(self, lines: list[Any], data: pd.DataFrame, level: str, kind: str) -> list[dict[str, Any]]:
        if not lines:
            return []
        points: OrderedDict[int, dict[str, Any]] = OrderedDict()
        for position, line in enumerate(lines):
            endpoints = [(line.get_begin_klu(), "bottom" if line.is_up() else "top")]
            endpoints.append((line.get_end_klu(), "top" if line.is_up() else "bottom"))
            for endpoint_index, (klu, pivot_kind) in enumerate(endpoints):
                index = _safe_index(klu.idx, len(data))
                if index in points:
                    continue
                owner = lines[max(0, position - 1)] if endpoint_index == 0 and position > 0 else line
                confirmed_index = self._confirmation_index(owner, len(data))
                price = float(klu.high if pivot_kind == "top" else klu.low)
                points[index] = {
                    "id": _stable_id("chanpy-pivot", level, kind, pivot_kind, index),
                    "level": level,
                    "kind": pivot_kind,
                    "event_at": _iso(data.iloc[index]["time"]),
                    "confirmed_at": _iso(data.iloc[confirmed_index]["time"]),
                    "price": price,
                    "is_sure": bool(owner.is_sure if hasattr(owner, "is_sure") and not callable(owner.is_sure) else owner.is_sure()),
                    "source_kind": kind,
                }
        return list(points.values())

    @staticmethod
    def _confirmation_index(line: Any, size: int) -> int:
        event_index = _safe_index(line.get_end_klu().idx, size)
        evidence_index = event_index
        eigen = getattr(line, "eigen_fx", None)
        evidence_line = getattr(eigen, "last_evidence_bi", None) if eigen is not None else None
        if evidence_line is not None:
            evidence_index = max(evidence_index, int(evidence_line.get_end_klu().idx))
        end_klc = getattr(line, "end_klc", None)
        next_klc = getattr(end_klc, "next", None) if end_klc is not None else None
        if next_klc is not None and len(next_klc) > 0:
            evidence_index = max(evidence_index, int(next_klc[0].idx))
        return _safe_index(evidence_index, size)

    @staticmethod
    def _center_record(center: Any, data: pd.DataFrame, level: str, component_type: str) -> dict[str, Any]:
        count = int(center.end_bi.idx - center.begin_bi.idx + 1)
        start = _safe_index(center.begin.idx, len(data))
        end = _safe_index(center.end.idx, len(data))
        return {
            "id": _stable_id("chanpy-center", level, component_type, center.begin.idx, center.end.idx),
            "level": level,
            "start_at": _iso(data.iloc[start]["time"]),
            "end_at": _iso(data.iloc[end]["time"]),
            "zd": float(center.low),
            "zg": float(center.high),
            "dd": float(center.peak_low),
            "gg": float(center.peak_high),
            "state": "completed" if center.is_sure else "active",
            "stroke_count": count,
            "component_type": component_type,
            "component_count": count,
            "extension_count": max(0, count - 3),
            "promoted_from": [],
            "is_sure": bool(center.is_sure),
        }

    def _line_metrics(self, line: Any, data: pd.DataFrame, name: str) -> dict[str, Any]:
        start = _safe_index(line.get_begin_klu().idx, len(data))
        end = _safe_index(line.get_end_klu().idx, len(data))
        if start > end:
            start, end = end, start
        direction = "down" if line.is_down() else "up"
        macd_values = data.iloc[start : end + 1]["macd"].astype(float).tolist()
        dif_values = data.iloc[start : end + 1]["dif"].astype(float).tolist()
        relevant = [abs(value) for value in macd_values if (value < 0 if direction == "down" else value > 0)]
        volumes = data.iloc[start : end + 1]["volume"].astype(float)
        amounts = data.iloc[start : end + 1]["amount"].astype(float)
        return {
            "name": name,
            "start": start,
            "end": end,
            "startTime": _iso(data.iloc[start]["time"]),
            "endTime": _iso(data.iloc[end]["time"]),
            "startValue": float(line.get_begin_val()),
            "endValue": float(line.get_end_val()),
            "direction": direction,
            "bars": end - start + 1,
            "priceMove": abs(float(line.get_end_val()) - float(line.get_begin_val())),
            "macdArea": float(sum(relevant)),
            "macdPeak": float(max(relevant, default=0.0)),
            "difExtreme": float(abs(min(dif_values)) if direction == "down" else abs(max(dif_values))),
            "volumeTotal": float(volumes.sum()),
            "volumeAverage": float(volumes.mean()),
            "amountAverage": float(amounts.mean()),
        }

    def _signals(
        self,
        points: Any,
        is_segment: bool,
        line_list: list[Any],
        parent_segments: list[Any],
        data: pd.DataFrame,
        level: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        history: list[dict[str, Any]] = []
        for point in points:
            evidence = self._signal_evidence(point, is_segment, line_list, parent_segments, data)
            native_types = evidence["native_types"]
            primary_type = evidence["primary_type"]
            family = "1" if primary_type in {"1", "1p"} else "2" if primary_type in {"2", "2s"} else "3"
            side = "B" if point.is_buy else "S"
            label = f"{family}{side}"
            display_label = f"{'段' if is_segment else '笔'}{side}{','.join(native_types)}"
            signal = self._signal_record(
                point, label, display_label, primary_type, is_segment, data, level, evidence
            )
            history.append(signal)
        self._apply_signal_dependencies(history)
        self._apply_signal_lifecycle(history, data)
        active = [signal for signal in history if signal["lifecycle"]["state"] == "confirmed"]
        return active, history

    @staticmethod
    def _apply_signal_dependencies(history: list[dict[str, Any]]) -> None:
        by_line_index = {
            signal["evidence"]["line_index"]: signal
            for signal in history
        }
        for signal in history:
            dependency = signal["evidence"].get("dependency")
            if not dependency or not dependency.get("required"):
                continue
            parent = by_line_index.get(dependency.get("parent_line_index"))
            if parent is None:
                dependency.update({
                    "status": "missing",
                    "status_label": "缺少关联一类点",
                    "conclusion": "原生二类点没有找到可追溯的一类点，不能进入正式信号。",
                })
                signal["lifecycle"].update({"state": "candidate", "confirmed_at": None})
                signal["confidence"] = 0.35
                continue

            parent_state = parent["lifecycle"]["state"]
            dependency.update({
                "parent_signal_id": parent["id"],
                "parent_display_label": parent["display_label"],
                "parent_event_at": parent["lifecycle"]["event_at"],
                "parent_state": parent_state,
            })
            if parent_state == "confirmed":
                dependency.update({
                    "status": "confirmed",
                    "status_label": "关联一类点已确认",
                    "conclusion": "关联一类点通过严格复核，二类点可继续按回撤结构判定。",
                })
                continue

            if parent_state == "invalidated":
                dependency.update({
                    "status": "invalidated",
                    "status_label": "关联一类点已失效",
                    "conclusion": "关联一类点未通过严格复核，依赖它的二类点同步失效。",
                })
                signal["lifecycle"].update({
                    "state": "invalidated",
                    "confirmed_at": None,
                    "invalidated_at": signal["lifecycle"]["detected_at"],
                })
            else:
                dependency.update({
                    "status": "pending",
                    "status_label": "关联一类点仍是候选",
                    "conclusion": "关联一类点尚未通过严格复核，依赖它的二类点只能保留为候选。",
                })
                signal["lifecycle"].update({
                    "state": "candidate",
                    "confirmed_at": None,
                    "invalidated_at": None,
                })
            signal["confidence"] = 0.45

    @staticmethod
    def _apply_signal_lifecycle(history: list[dict[str, Any]], data: pd.DataFrame) -> None:
        """Retire confirmed signals only after a visible close breaks their risk guard."""
        by_line_index = {
            signal["evidence"]["line_index"]: signal
            for signal in history
        }

        # A second-class point belongs to its first-class chain and therefore
        # uses the parent's extreme as the chain-level invalidation boundary.
        for signal in history:
            dependency = signal["evidence"].get("dependency")
            if not dependency or not dependency.get("required"):
                continue
            parent = by_line_index.get(dependency.get("parent_line_index"))
            if parent is not None:
                signal["risk_guard"] = float(parent["risk_guard"])

        times = pd.to_datetime(data["time"])
        for signal in history:
            lifecycle = signal["lifecycle"]
            if lifecycle["state"] != "confirmed":
                continue
            guard = float(signal["risk_guard"])
            detected_at = pd.Timestamp(lifecycle["detected_at"])
            future = data.loc[times > detected_at]
            if signal["side"] == "buy":
                breaches = future.loc[future["close"] < guard]
                rule = "收盘价有效跌破信号链风险线"
            else:
                breaches = future.loc[future["close"] > guard]
                rule = "收盘价有效升破信号链风险线"
            invalidated_at = None if breaches.empty else _iso(breaches.iloc[0]["time"])
            signal["evidence"]["lifecycle_audit"] = {
                "risk_guard": guard,
                "rule": rule,
                "invalidated_at": invalidated_at,
            }
            if invalidated_at is None:
                continue
            lifecycle.update({
                "state": "invalidated",
                "invalidated_at": invalidated_at,
            })

        # Refresh dependency evidence after later bars have retired a parent.
        for signal in history:
            dependency = signal["evidence"].get("dependency")
            if not dependency or not dependency.get("required"):
                continue
            parent = by_line_index.get(dependency.get("parent_line_index"))
            if parent is None:
                continue
            parent_state = parent["lifecycle"]["state"]
            dependency["parent_state"] = parent_state
            if parent_state != "invalidated":
                continue
            dependency.update({
                "status": "invalidated",
                "status_label": "关联一类点已失效",
                "conclusion": "关联一类点后来跌破或升破风险线，依赖它的二类点已退出当前有效信号。",
            })
            if signal["lifecycle"]["state"] == "confirmed":
                signal["lifecycle"].update({
                    "state": "invalidated",
                    "invalidated_at": parent["lifecycle"]["invalidated_at"],
                })

    def _signal_record(
        self,
        point: Any,
        label: str,
        display_label: str,
        native_type: str,
        is_segment: bool,
        data: pd.DataFrame,
        level: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        line = point.bi
        event_index = _safe_index(point.klu.idx, len(data))
        detected_index = self._confirmation_index(line, len(data))
        is_sure = bool(line.is_sure if hasattr(line, "is_sure") and not callable(line.is_sure) else line.is_sure())
        audit = evidence["divergence_audit"]
        if native_type in {"1", "1p"}:
            confirmed = is_sure and audit["status"] == "confirmed"
            state = "confirmed" if confirmed else "candidate" if audit["status"] == "insufficient" else "invalidated"
        else:
            confirmed = is_sure
            state = "confirmed" if confirmed else "candidate"
        price = float(point.klu.low if point.is_buy else point.klu.high)
        center = evidence.get("center")
        if center:
            structure_guard = float(center["zg"] if point.is_buy else center["zd"])
        else:
            structure_guard = price
        scope = "segment" if is_segment else "stroke"
        return {
            "id": _stable_id(
                "chanpy-signal", level, scope, display_label, data.iloc[event_index]["time"]
            ),
            "level": f"{level}段" if is_segment else level,
            "label": label,
            "display_label": display_label,
            "side": "buy" if point.is_buy else "sell",
            "price": price,
            "confidence": 0.82 if confirmed and native_type in {"1", "1p"} else 0.72 if confirmed else 0.45,
            "divergence_class": (
                "trend_divergence" if native_type == "1" else
                "consolidation_divergence" if native_type == "1p" else
                "structural_retest" if native_type in {"2", "2s"} else
                "center_non_return"
            ),
            "structure_guard": structure_guard,
            "risk_guard": price,
            "lifecycle": {
                "state": state,
                "event_at": _iso(data.iloc[event_index]["time"]),
                "detected_at": _iso(data.iloc[detected_index]["time"]),
                "confirmed_at": _iso(data.iloc[detected_index]["time"]) if confirmed else None,
                "invalidated_at": _iso(data.iloc[detected_index]["time"]) if state == "invalidated" else None,
                "expired_at": None,
            },
            "evidence": {**copy.deepcopy(evidence), "native_type": native_type, "scope": scope},
        }

    def _signal_evidence(
        self,
        point: Any,
        is_segment: bool,
        line_list: list[Any],
        parent_segments: list[Any],
        data: pd.DataFrame,
    ) -> dict[str, Any]:
        native_types = [item.value for item in point.type]
        primary = next((item for item in ("1", "1p", "2", "2s", "3a", "3b") if item in native_types), native_types[0])
        line = point.bi
        reference_line = None
        center = None
        comparison_kind = "structure"
        basis = "该点由 chan.py 形态结构生成，不以背驰作为直接条件。"
        if primary == "1":
            parent = self._parent_segment(line, parent_segments)
            if parent is not None and parent.zs_lst:
                center = parent.zs_lst[-1]
                reference_line = center.get_bi_in()
            comparison_kind = "divergence"
            basis = "比较最后一个中枢的进入段与离开段；价格创新值且至少两项动能证据明确减弱才确认背驰。"
        elif primary == "1p":
            if line.idx >= 2:
                reference_line = line_list[line.idx - 2]
            comparison_kind = "divergence"
            basis = "盘整背驰比较相隔一段反向走势的前后两段同向结构。"
        elif primary in {"2", "2s"}:
            related = point.relate_bsp1
            if related is not None and related.bi.idx + 1 < len(line_list):
                reference_line = line_list[related.bi.idx + 1]
            comparison_kind = "retrace"
            basis = "二类点检查一类点后的回撤或反抽是否守住结构保护价；正式确认还要求关联一类点通过严格复核。"
        elif primary in {"3a", "3b"}:
            center = self._third_center(primary, line, point, parent_segments)
            if line.idx > 0 and line.idx - 1 < len(line_list):
                reference_line = line_list[line.idx - 1]
            comparison_kind = "center_non_return"
            basis = "三类点检查离开中枢后的首次回踩或反抽是否回到中枢。"
        if center is None:
            combined = next((item for item in ("3a", "3b") if item in native_types), None)
            if combined:
                center = self._third_center(combined, line, point, parent_segments)

        test = self._line_metrics(line, data, "检验段")
        reference = self._line_metrics(reference_line, data, "对照段") if reference_line is not None else None
        third_structure = None
        if primary in {"3a", "3b"} and center is not None:
            buy = bool(point.is_buy)
            boundary = float(center.high if buy else center.low)
            retrace_extreme = float(line.get_end_val())
            clearance = retrace_extreme - boundary if buy else boundary - retrace_extreme
            third_structure = {
                "side": "buy" if buy else "sell",
                "center_boundary_name": "ZG" if buy else "ZD",
                "center_boundary": boundary,
                "departure": reference,
                "retrace": test,
                "retrace_extreme": retrace_extreme,
                "holds_center": clearance >= 0,
                "clearance": clearance,
                "clearance_ratio": _ratio(clearance, abs(boundary)),
                "rule": (
                    "向上离开中枢后，首次回踩低点不低于中枢上沿 ZG。"
                    if buy else
                    "向下离开中枢后，首次反抽高点不高于中枢下沿 ZD。"
                ),
            }
        ratios: dict[str, float | None] = {}
        audit = {
            "status": "not_applicable",
            "status_label": "非背驰类结构点",
            "price_extension": None,
            "momentum_votes": None,
            "required_votes": REQUIRED_MOMENTUM_VOTES,
            "weakening_ratio": WEAKENING_RATIO,
            "macd_area_weakening": None,
            "macd_peak_weakening": None,
            "dif_weakening": None,
            "volume_contracting": None,
            "conclusion": "该类型不以背驰作为直接成立条件。",
        }
        if reference is not None and comparison_kind != "center_non_return":
            ratios = {
                "price_move": _ratio(test["priceMove"], reference["priceMove"]),
                "macd_area": _ratio(test["macdArea"], reference["macdArea"]),
                "macd_peak": _ratio(test["macdPeak"], reference["macdPeak"]),
                "dif_extreme": _ratio(test["difExtreme"], reference["difExtreme"]),
                "volume_average": _ratio(test["volumeAverage"], reference["volumeAverage"]),
            }
            if comparison_kind == "divergence":
                price_extension = (
                    test["endValue"] < reference["endValue"]
                    if test["direction"] == "down"
                    else test["endValue"] > reference["endValue"]
                )
                checks = {
                    "macd_area_weakening": ratios["macd_area"] is not None and ratios["macd_area"] <= WEAKENING_RATIO,
                    "macd_peak_weakening": ratios["macd_peak"] is not None and ratios["macd_peak"] <= WEAKENING_RATIO,
                    "dif_weakening": ratios["dif_extreme"] is not None and ratios["dif_extreme"] <= WEAKENING_RATIO,
                }
                votes = sum(checks.values())
                if not price_extension:
                    status, label, conclusion = "unsupported", "不支持背驰", "价格未创新值。"
                elif votes >= REQUIRED_MOMENTUM_VOTES:
                    status, label, conclusion = "confirmed", "背驰确认", f"三项动能证据中有 {votes} 项明确减弱。"
                elif votes == 1:
                    status, label, conclusion = "insufficient", "证据不足", "仅一项动能证据明确减弱。"
                else:
                    status, label, conclusion = "unsupported", "不支持背驰", "动能证据没有明确减弱。"
                audit = {
                    "status": status,
                    "status_label": label,
                    "price_extension": bool(price_extension),
                    "momentum_votes": votes,
                    "required_votes": REQUIRED_MOMENTUM_VOTES,
                    "weakening_ratio": WEAKENING_RATIO,
                    **checks,
                    "volume_contracting": (
                        ratios["volume_average"] is not None and ratios["volume_average"] < 1
                    ),
                    "conclusion": conclusion,
                }

        dependency = None
        if primary in {"2", "2s"}:
            related = point.relate_bsp1
            dependency = {
                "required": True,
                "parent_line_index": related.bi.idx if related is not None else None,
                "status": "unresolved",
            }

        return {
            "engine": "chan.py",
            "engine_commit": CHANPY_COMMIT,
            "native_types": native_types,
            "primary_type": primary,
            "comparison_kind": comparison_kind,
            "basis": basis,
            "reference": reference,
            "test": test,
            "third_structure": third_structure,
            "ratios": ratios,
            "divergence_audit": audit,
            "center": self._center_record(center, data, "native", "stroke") if center is not None else None,
            "native_features": {key: value for key, value in point.features.items()},
            "line_index": line.idx,
            "dependency": dependency,
        }

    @staticmethod
    def _parent_segment(line: Any, parent_segments: list[Any]) -> Any | None:
        index = getattr(line, "seg_idx", None)
        return parent_segments[index] if index is not None and 0 <= index < len(parent_segments) else None

    def _third_center(self, primary: str, line: Any, point: Any, parent_segments: list[Any]) -> Any | None:
        if primary == "3a":
            parent = self._parent_segment(line, parent_segments)
            if parent is None:
                return None
            for center in parent.zs_lst:
                if center.bi_out is not None and center.bi_out.idx + 1 == line.idx:
                    return center
            return parent.zs_lst[0] if parent.zs_lst else None
        related = point.relate_bsp1
        if related is None:
            return None
        parent = self._parent_segment(related.bi, parent_segments)
        return parent.zs_lst[-1] if parent is not None and parent.zs_lst else None

    @staticmethod
    def _signal_sort_key(signal: dict[str, Any]) -> tuple[str, str, str]:
        return signal["lifecycle"]["event_at"], signal["level"], signal["label"]

    @staticmethod
    def _current_state(
        data: pd.DataFrame,
        centers: list[dict[str, Any]],
        strokes: list[dict[str, Any]],
        segments: list[dict[str, Any]],
        signals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        price = float(data.iloc[-1]["close"])
        center = centers[-1] if centers else None
        if center and price > float(center["zg"]):
            state = "up_leave_confirmed"
            observation = "价格位于最近中枢上方，等待首次回踩是否守住 ZG。"
        elif center and price < float(center["zd"]):
            state = "down_leave_confirmed"
            observation = "价格位于最近中枢下方，等待首次反抽是否受制于 ZD。"
        elif center:
            state = "center_balance"
            observation = "价格仍在最近中枢内，等待有效离开。"
        elif strokes:
            state = f"trend_{strokes[-1]['direction']}"
            observation = "中枢结构不足，继续跟踪确认笔。"
        else:
            state = "insufficient_structure"
            observation = "确认结构不足，暂不下结论。"
        return {
            "state": state,
            "price": round(price, 6),
            "active_center": center,
            "last_stroke": strokes[-1] if strokes else None,
            "last_segment": segments[-1] if segments else None,
            "last_signal": signals[-1] if signals else None,
            "risk_line": (
                float(center["zg"]) if center and price > float(center["zg"])
                else float(center["zd"]) if center and price < float(center["zd"])
                else None
            ),
            "observation": observation,
        }
