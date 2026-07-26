from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd


ENGINE_VERSION = "cross-level-v0.1.0"


def _iso(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


class CrossLevelReversalEngine:
    """Confirm a 5m first-class point only after it breaks a 30m structure boundary."""

    def analyze(
        self,
        execution_chan: dict[str, Any],
        decision_chan: dict[str, Any],
        execution_data: pd.DataFrame,
        decision_data: pd.DataFrame,
    ) -> dict[str, Any]:
        execution_data = self._with_macd(execution_data)
        execution_times = pd.to_datetime(execution_data["time"])
        decision_times = pd.to_datetime(decision_data["time"])
        events: list[dict[str, Any]] = []

        for source in execution_chan.get("signal_history", []):
            event = self._event_from_source(
                source,
                execution_chan,
                decision_chan,
                execution_data,
                decision_data,
                execution_times,
                decision_times,
            )
            if event is not None:
                events.append(event)

        events.sort(key=lambda item: (item["lifecycle"]["event_at"], item["direction"]))
        active = [item for item in events if item["lifecycle"]["state"] != "invalidated"]
        return {
            "version": ENGINE_VERSION,
            "source_level": "5m",
            "target_level": "30m",
            "events": events,
            "active": active,
            "summary": {
                "total": len(events),
                "candidate": sum(item["lifecycle"]["state"] == "candidate" for item in events),
                "triggered": sum(item["lifecycle"]["state"] == "triggered" for item in events),
                "confirmed": sum(item["lifecycle"]["state"] == "confirmed" for item in events),
                "invalidated": sum(item["lifecycle"]["state"] == "invalidated" for item in events),
            },
        }

    @staticmethod
    def _with_macd(frame: pd.DataFrame) -> pd.DataFrame:
        data = frame.copy().reset_index(drop=True)
        ema12 = data["close"].ewm(span=12, adjust=False).mean()
        ema26 = data["close"].ewm(span=26, adjust=False).mean()
        data["dif"] = ema12 - ema26
        data["dea"] = data["dif"].ewm(span=9, adjust=False).mean()
        data["macd"] = (data["dif"] - data["dea"]) * 2
        return data

    def _event_from_source(
        self,
        source: dict[str, Any],
        execution_chan: dict[str, Any],
        decision_chan: dict[str, Any],
        execution_data: pd.DataFrame,
        decision_data: pd.DataFrame,
        execution_times: pd.Series,
        decision_times: pd.Series,
    ) -> dict[str, Any] | None:
        evidence = source.get("evidence", {})
        lifecycle = source.get("lifecycle", {})
        primary_type = evidence.get("primary_type") or evidence.get("native_type")
        detected_at = lifecycle.get("confirmed_at")
        if primary_type not in {"1", "1p"} or detected_at is None:
            return None

        scope = evidence.get("scope", "stroke")
        lines = execution_chan.get("segments" if scope == "segment" else "strokes", [])
        line_index = evidence.get("line_index")
        if not isinstance(line_index, int) or not 0 <= line_index < len(lines):
            return None
        source_line = lines[line_index]
        buy = source.get("side") == "buy" or str(source.get("label", "")).endswith("B")
        expected_line_direction = "down" if buy else "up"
        if source_line.get("direction") != expected_line_direction:
            return None

        event_at = pd.Timestamp(lifecycle["event_at"])
        detected = pd.Timestamp(detected_at)
        source_price = float(source["price"])
        direction = "up" if buy else "down"
        boundary_pivot = self._latest_confirmed_segment_boundary(
            event_at,
            detected,
            "top" if buy else "bottom",
            execution_chan.get("segment_pivots", []),
        )
        if boundary_pivot is None:
            return None
        boundary = float(boundary_pivot["price"])
        context = self._containing_decision_stroke(
            event_at,
            expected_line_direction,
            decision_chan.get("strokes", []),
        )

        future_execution = execution_data.loc[execution_times > detected]
        if buy:
            trigger_rows = future_execution.loc[future_execution["close"] > boundary]
            breach_rows = future_execution.loc[future_execution["close"] < source_price]
        else:
            trigger_rows = future_execution.loc[future_execution["close"] < boundary]
            breach_rows = future_execution.loc[future_execution["close"] > source_price]

        trigger_at = None if trigger_rows.empty else pd.Timestamp(trigger_rows.iloc[0]["time"])
        breach_at = None if breach_rows.empty else pd.Timestamp(breach_rows.iloc[0]["time"])
        if trigger_at is not None and breach_at is not None and breach_at <= trigger_at:
            trigger_at = None

        context_confirmed_at = (
            pd.Timestamp(context["confirmed_at"])
            if context is not None and context.get("is_sure") and context.get("confirmed_at")
            else None
        )
        confirmed_at = None
        if trigger_at is not None and context_confirmed_at is not None:
            confirmation_start = max(trigger_at, context_confirmed_at)
            eligible = decision_data.loc[decision_times >= confirmation_start]
            if buy:
                confirmation_rows = eligible.loc[eligible["close"] > boundary]
            else:
                confirmation_rows = eligible.loc[eligible["close"] < boundary]
            if not confirmation_rows.empty:
                candidate_confirmation = pd.Timestamp(confirmation_rows.iloc[0]["time"])
                if breach_at is None or candidate_confirmation < breach_at:
                    confirmed_at = candidate_confirmation

        if breach_at is not None and (confirmed_at is None or breach_at > confirmed_at):
            state = "invalidated"
            invalidated_at = breach_at
        elif confirmed_at is not None:
            state = "confirmed"
            invalidated_at = None
        elif trigger_at is not None:
            state = "triggered"
            invalidated_at = None
        else:
            state = "candidate" if breach_at is None else "invalidated"
            invalidated_at = breach_at

        trigger_evidence = self._trigger_evidence(trigger_at, execution_data, execution_times)
        label = f"5→30 {'向上' if buy else '向下'}转折"
        return {
            "id": _stable_id("cross-level", source["id"], "30m"),
            "source_level": "5m",
            "target_level": "30m",
            "direction": direction,
            "label": label,
            "source_signal_id": source["id"],
            "source_signal_label": source.get("display_label", source.get("label", "")),
            "source_price": source_price,
            "break_boundary": boundary,
            "risk_guard": source_price,
            "lifecycle": {
                "state": state,
                "event_at": _iso(event_at),
                "detected_at": _iso(detected),
                "triggered_at": _iso(trigger_at) if trigger_at is not None else None,
                "confirmed_at": _iso(confirmed_at) if confirmed_at is not None else None,
                "invalidated_at": _iso(invalidated_at) if invalidated_at is not None else None,
                "expired_at": None,
            },
            "evidence": {
                "rule": "5m一类点确认后，价格先突破当时已确认的5m线段端点，再由30m收盘确认。",
                "source_scope": scope,
                "source_native_type": primary_type,
                "source_detected_at": _iso(detected),
                "source_line": source_line,
                "break_boundary_pivot": boundary_pivot,
                "decision_context": context,
                "decision_context_confirmed_at": (
                    _iso(context_confirmed_at) if context_confirmed_at is not None else None
                ),
                "trigger": trigger_evidence,
            },
        }

    @staticmethod
    def _latest_confirmed_segment_boundary(
        event_at: pd.Timestamp,
        detected_at: pd.Timestamp,
        kind: str,
        pivots: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        matches = [
            item
            for item in pivots
            if item.get("kind") == kind
            and item.get("is_sure") is True
            and pd.Timestamp(item["event_at"]) < event_at
            and pd.Timestamp(item["confirmed_at"]) <= detected_at
        ]
        return matches[-1] if matches else None

    @staticmethod
    def _containing_decision_stroke(
        event_at: pd.Timestamp,
        direction: str,
        strokes: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        matches = [
            item
            for item in strokes
            if item.get("direction") == direction
            and pd.Timestamp(item["start_at"]) <= event_at <= pd.Timestamp(item["end_at"])
        ]
        return matches[-1] if matches else None

    @staticmethod
    def _trigger_evidence(
        trigger_at: pd.Timestamp | None,
        data: pd.DataFrame,
        times: pd.Series,
    ) -> dict[str, Any] | None:
        if trigger_at is None:
            return None
        indices = data.index[times == trigger_at]
        if indices.empty:
            return None
        index = int(indices[0])
        row = data.loc[index]
        prior_volume = data.loc[max(0, index - 20): index - 1, "volume"]
        volume_ratio = None
        if not prior_volume.empty and float(prior_volume.mean()) > 0:
            volume_ratio = float(row["volume"]) / float(prior_volume.mean())
        return {
            "time": _iso(trigger_at),
            "close": float(row["close"]),
            "volume_ratio_20": volume_ratio,
            "dif": float(row["dif"]),
            "dea": float(row["dea"]),
            "macd": float(row["macd"]),
        }
