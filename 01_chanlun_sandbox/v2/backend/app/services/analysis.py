from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import AppConfig, normalize_profile, profile_values
from ..data_service import DataService
from ..engines.chanpy_engine import ChanPyEngine
from ..engines.fusion import FusionEngine
from ..engines.chan_radar import ChanRadarAdapter
from ..models import AnalysisResponse, AnalyzeRequest


class AnalysisService:
    def __init__(self, config: AppConfig, data: DataService):
        self.config = config
        self.data = data
        self.chan_engine = ChanPyEngine()
        self.radar_engine = ChanRadarAdapter()
        self.fusion_engine = FusionEngine()
        self._cache: dict[str, AnalysisResponse] = {}
        self._cache_lock = threading.RLock()

    def analyze(self, request: AnalyzeRequest) -> AnalysisResponse:
        normalized_symbol = self.data.normalize_symbol(request.symbol)
        profile = normalize_profile(request.profile)
        execution, execution_quality = self.data.load_frame(normalized_symbol, request.execution_level, request.as_of)
        decision, decision_quality = self.data.load_frame(normalized_symbol, request.decision_level, request.as_of)
        if request.end is not None:
            execution = execution.loc[execution["time"] <= pd.Timestamp(request.end)].reset_index(drop=True)
            decision = decision.loc[decision["time"] <= pd.Timestamp(request.end)].reset_index(drop=True)
        if execution.empty or decision.empty:
            raise ValueError("指定时间范围没有足够行情")
        # The execution clock is authoritative. A 30m decision bar may naturally
        # lag the latest completed 5m bar without making that 5m evidence future data.
        as_of = pd.Timestamp(execution.iloc[-1]["time"])
        execution = execution.loc[execution["time"] <= as_of].reset_index(drop=True)
        decision = decision.loc[decision["time"] <= as_of].reset_index(drop=True)
        # `start` only controls the viewport. Structure and indicators must
        # inherit every bar available before the requested display window.
        digest = self.data.data_hash([execution, decision])
        config_hash = self.config.config_hash(profile, request.research_overrides)
        cache_key = json.dumps(
            {
                "symbol": normalized_symbol,
                "execution": request.execution_level,
                "decision": request.decision_level,
                "display": request.display_level,
                "start": request.start.isoformat() if request.start else None,
                "end": request.end.isoformat() if request.end else None,
                "as_of": as_of.isoformat(),
                "profile": profile,
                "benchmark": request.benchmark,
                "invalidated": request.include_invalidated,
                "overrides": request.research_overrides,
                "data_hash": digest,
            },
            sort_keys=True,
        )
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached:
                return cached.model_copy(deep=True)
        values = profile_values(profile, request.research_overrides)
        values["profile_name"] = profile
        higher = self._to_daily(decision)
        execution_chan = self.chan_engine.analyze(execution, request.execution_level, values)
        decision_chan = self.chan_engine.analyze(decision, request.decision_level, values)
        higher_chan = self.chan_engine.analyze(higher, "1d", values)
        execution_radar = self.radar_engine.analyze(execution_chan, request.execution_level)
        decision_radar = self.radar_engine.analyze(decision_chan, request.decision_level)
        higher_radar = self.radar_engine.analyze(higher_chan, "1d")
        if request.display_level == request.execution_level:
            plan_chan, plan_context = execution_chan, decision_chan
        else:
            plan_chan, plan_context = decision_chan, higher_chan
        fusion, plan = self.fusion_engine.analyze(plan_chan, plan_context)
        # Retain empty compatibility fields for existing snapshots and clients.
        wyckoff = {"status": "removed", "events": [], "features": {"series": {}}}
        wave = {"status": "removed", "primary": None, "alternate": None, "context": []}
        display_frame = execution if request.display_level == request.execution_level else decision
        display_chan = execution_chan if request.display_level == request.execution_level else decision_chan
        visible, start_index = self._visible_frame(display_frame, request.start)
        active_chan = self._prepare_chan(execution_chan, visible.iloc[0]["time"], request.include_invalidated)
        decision_view = self._prepare_chan(decision_chan, visible.iloc[0]["time"], request.include_invalidated)
        higher_view = self._prepare_chan(higher_chan, visible.iloc[0]["time"], request.include_invalidated)
        self._merge_promoted_signals(
            decision_view,
            execution_chan.get("promoted_signals", []),
            visible.iloc[0]["time"],
            request.include_invalidated,
        )
        self._merge_promoted_signals(
            higher_view,
            decision_chan.get("promoted_signals", []),
            visible.iloc[0]["time"],
            request.include_invalidated,
        )
        decision_view["inherited_centers"] = self._inherited_centers(
            execution_chan.get("promoted_centers", []), decision_view.get("centers", []), visible.iloc[0]["time"]
        )
        higher_view["inherited_centers"] = self._inherited_centers(
            decision_chan.get("promoted_centers", []), higher_view.get("centers", []), visible.iloc[0]["time"]
        )
        indicators = {
            "macd": {
                key: values_list[start_index:]
                for key, values_list in display_chan["macd"].items()
            },
            "wyckoff": {},
        }
        name = next(
            (item["name"] for item in self.data.list_stocks() if item["symbol"] == normalized_symbol),
            "",
        )
        warnings: list[str] = []
        response = AnalysisResponse(
            schema_version=self.config.schema_version,
            model_version=self.config.model_version,
            config_hash=config_hash,
            data_hash=digest,
            as_of=as_of.to_pydatetime(),
            visible_bar_end=pd.Timestamp(visible.iloc[-1]["time"]).to_pydatetime(),
            symbol=normalized_symbol,
            stock_name=name,
            levels={"decision": request.decision_level, "execution": request.execution_level, "higher": "1d", "display": request.display_level},
            data_quality={"execution": execution_quality, "decision": decision_quality, "higher": {"status": "derived", "rows": len(higher)}},
            bars=self.data.market_bars(visible),
            indicators=indicators,
            radar={
                "version": execution_radar["version"],
                "execution": self._prepare_radar(execution_radar, visible.iloc[0]["time"]),
                "decision": self._prepare_radar(decision_radar, visible.iloc[0]["time"]),
                "higher": self._prepare_radar(higher_radar, visible.iloc[0]["time"]),
            },
            chan={"execution": active_chan, "decision": decision_view, "higher": higher_view},
            wyckoff=wyckoff,
            wave=wave,
            fusion=fusion,
            plan=plan,
            warnings=warnings,
        )
        with self._cache_lock:
            if len(self._cache) >= 32:
                self._cache.pop(next(iter(self._cache)))
            self._cache[cache_key] = response.model_copy(deep=True)
        return response

    @staticmethod
    def _to_daily(frame: pd.DataFrame) -> pd.DataFrame:
        daily = frame.copy()
        daily["trade_day"] = daily["time"].dt.normalize()
        daily = (
            daily.groupby("trade_day", as_index=False)
            .agg(
                time=("time", "last"),
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
                amount=("amount", "sum"),
            )
        )
        denominator = daily["volume"].replace(0, pd.NA)
        daily["vwap"] = (daily["amount"].where(daily["amount"] > 0, daily["close"] * daily["volume"]) / denominator).fillna(daily["close"])
        return daily

    def _visible_frame(self, frame: pd.DataFrame, start: datetime | None) -> tuple[pd.DataFrame, int]:
        if start is None:
            days = frame["time"].dt.normalize().drop_duplicates().tolist()
            cutoff = days[max(0, len(days) - self.config.visible_trading_days)]
        else:
            cutoff = pd.Timestamp(start)
        mask = frame["time"] >= cutoff
        indices = frame.index[mask]
        if indices.empty:
            return frame.tail(1).reset_index(drop=True), len(frame) - 1
        start_index = int(indices[0])
        return frame.loc[mask].reset_index(drop=True), start_index

    @staticmethod
    def _prepare_chan(chan: dict[str, Any], visible_start: pd.Timestamp, include_invalidated: bool) -> dict[str, Any]:
        result = copy.deepcopy(chan)
        all_signals = result.get("signal_history", result.get("signals", []))
        result["signal_history"] = all_signals
        result["signals"] = [
            signal
            for signal in result.get("signals", [])
            if pd.Timestamp(signal["lifecycle"]["event_at"]) >= visible_start
            and (include_invalidated or signal["lifecycle"]["state"] != "invalidated")
        ]
        result["centers"] = [
            center for center in result.get("centers", []) if pd.Timestamp(center["end_at"]) >= visible_start
        ]
        result["pivots"] = [
            pivot for pivot in result.get("pivots", []) if pd.Timestamp(pivot["event_at"]) >= visible_start
        ]
        result["strokes"] = [
            stroke for stroke in result.get("strokes", []) if pd.Timestamp(stroke["end_at"]) >= visible_start
        ]
        result["segment_pivots"] = [
            pivot for pivot in result.get("segment_pivots", []) if pd.Timestamp(pivot["event_at"]) >= visible_start
        ]
        result["segments"] = [
            segment for segment in result.get("segments", []) if pd.Timestamp(segment["end_at"]) >= visible_start
        ]
        result["segment_centers"] = [
            center for center in result.get("segment_centers", []) if pd.Timestamp(center["end_at"]) >= visible_start
        ]
        result["promoted_centers"] = [
            center for center in result.get("promoted_centers", []) if pd.Timestamp(center["end_at"]) >= visible_start
        ]
        result.pop("macd", None)
        return result

    @staticmethod
    def _prepare_radar(radar: dict[str, Any], visible_start: pd.Timestamp) -> dict[str, Any]:
        result = copy.deepcopy(radar)
        result["pivots"] = [
            item for item in result.get("pivots", []) if pd.Timestamp(item["event_at"]) >= visible_start
        ]
        result["swings"] = [
            item for item in result.get("swings", []) if pd.Timestamp(item["end_at"]) >= visible_start
        ]
        result["zones"] = [
            item for item in result.get("zones", []) if pd.Timestamp(item["end_at"]) >= visible_start
        ]
        result["events"] = [
            item for item in result.get("events", []) if pd.Timestamp(item["event_at"]) >= visible_start
        ]
        result["summary"] = {
            "confirmed_pivots": len(result["pivots"]),
            "confirmed_swings": len(result["swings"]),
            "balance_zones": len(result["zones"]),
            "confirmed_events": len(result["events"]),
        }
        return result

    @staticmethod
    def _merge_promoted_signals(
        target: dict[str, Any],
        promoted: list[dict[str, Any]],
        visible_start: pd.Timestamp,
        include_invalidated: bool,
    ) -> None:
        def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            unique: dict[tuple[str, str, str], dict[str, Any]] = {}
            for signal in items:
                lifecycle = signal["lifecycle"]
                key = (signal["level"], signal["label"], lifecycle["event_at"])
                previous = unique.get(key)
                current_rank = (lifecycle["state"] == "confirmed", float(signal.get("confidence", 0)))
                previous_rank = (
                    previous is not None and previous["lifecycle"]["state"] == "confirmed",
                    float(previous.get("confidence", 0)) if previous else 0,
                )
                if previous is None or current_rank > previous_rank:
                    unique[key] = copy.deepcopy(signal)
            return sorted(unique.values(), key=lambda item: (item["lifecycle"]["event_at"], item["label"]))

        target["signal_history"] = dedupe([*target.get("signal_history", []), *promoted])
        visible_promoted = [
            signal
            for signal in promoted
            if pd.Timestamp(signal["lifecycle"]["event_at"]) >= visible_start
            and (include_invalidated or signal["lifecycle"]["state"] != "invalidated")
        ]
        target["signals"] = dedupe([*target.get("signals", []), *visible_promoted])

    @staticmethod
    def _inherited_centers(
        promoted: list[dict[str, Any]],
        parent_centers: list[dict[str, Any]],
        visible_start: pd.Timestamp,
    ) -> list[dict[str, Any]]:
        inherited: list[dict[str, Any]] = []
        for candidate in promoted:
            if candidate.get("component_type") != "center":
                continue
            if pd.Timestamp(candidate["end_at"]) < visible_start:
                continue
            duplicate = any(
                pd.Timestamp(parent["start_at"]) <= pd.Timestamp(candidate["end_at"])
                and pd.Timestamp(candidate["start_at"]) <= pd.Timestamp(parent["end_at"])
                and max(float(parent["zd"]), float(candidate["zd"])) < min(float(parent["zg"]), float(candidate["zg"]))
                for parent in parent_centers
            )
            if not duplicate:
                inherited.append(copy.deepcopy(candidate))
        return inherited

    def export(self, request: AnalyzeRequest) -> dict[str, Any]:
        response = self.analyze(request)
        payload = response.model_dump(mode="json")
        compact = {
            "schema_version": payload["schema_version"],
            "model_version": payload["model_version"],
            "symbol": payload["symbol"],
            "as_of": payload["as_of"],
            "operation_level": payload["levels"]["decision"],
            "execution_level": payload["levels"]["execution"],
            "chan_state": payload["chan"]["execution"]["current"]["state"],
            "chan_signal": (payload["chan"]["execution"]["signals"] or [None])[-1],
            "radar_state": payload["radar"]["execution"]["current"],
            "radar_event": (payload["radar"]["execution"]["events"] or [None])[-1],
            "model_conflict": payload["fusion"]["conflicts"],
            "signal_grade": payload["fusion"]["grade"],
            "plan": payload["plan"],
            "data_hash": payload["data_hash"],
            "config_hash": payload["config_hash"],
        }
        filename = f"{response.symbol}_{response.as_of.strftime('%Y%m%d_%H%M')}.json"
        path: Path = self.config.export_dir / filename
        path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(path), "payload": compact}
