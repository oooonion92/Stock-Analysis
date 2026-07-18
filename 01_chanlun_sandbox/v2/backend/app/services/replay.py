from __future__ import annotations

from typing import Any

import pandas as pd

from ..data_service import DataService
from ..models import AnalyzeRequest, ReplayAdvanceRequest, ReplayCreateRequest
from ..storage import Storage
from .analysis import AnalysisService


class ReplayService:
    def __init__(self, storage: Storage, data: DataService, analysis: AnalysisService):
        self.storage = storage
        self.data = data
        self.analysis = analysis

    def create(self, request: ReplayCreateRequest) -> dict[str, Any]:
        analysis_data = request.analysis.model_dump(mode="json")
        analysis_data["as_of"] = request.initial_as_of.isoformat()
        session_id = self.storage.create_replay(analysis_data, request.initial_as_of.isoformat())
        result = self.analysis.analyze(AnalyzeRequest.model_validate(analysis_data))
        return {
            "session_id": session_id,
            "current_as_of": request.initial_as_of,
            "completed": False,
            "analysis": result,
        }

    def get(self, session_id: str) -> dict[str, Any] | None:
        session = self.storage.get_replay(session_id)
        if not session:
            return None
        request = dict(session["request"])
        request["as_of"] = session["current_as_of"]
        result = self.analysis.analyze(AnalyzeRequest.model_validate(request))
        return {
            "session_id": session_id,
            "current_as_of": session["current_as_of"],
            "completed": session["completed"],
            "analysis": result,
            "evaluation": self._evaluation(session, result) if session["completed"] else None,
        }

    def advance(self, session_id: str, advance: ReplayAdvanceRequest) -> dict[str, Any] | None:
        session = self.storage.get_replay(session_id)
        if not session:
            return None
        request_data = dict(session["request"])
        current = pd.Timestamp(session["current_as_of"])
        symbol = request_data["symbol"]
        level = request_data.get("execution_level", "5m")
        next_times = self.data.next_times(symbol, level, current)
        if not next_times:
            target = current
            completed = True
        elif advance.mode == "session_end":
            target = next_times[-1]
            completed = True
        elif advance.mode == "next_event":
            target = self._advance_to_event(request_data, current, next_times)
            completed = target == next_times[-1]
        else:
            index = min(len(next_times), advance.count) - 1
            target = next_times[index]
            completed = index == len(next_times) - 1
        self.storage.update_replay(session_id, pd.Timestamp(target).isoformat(), completed)
        return self.get(session_id)

    def _advance_to_event(self, request_data: dict[str, Any], current: pd.Timestamp, next_times: list[pd.Timestamp]) -> pd.Timestamp:
        baseline_request = dict(request_data)
        baseline_request["as_of"] = current.isoformat()
        baseline = self.analysis.analyze(AnalyzeRequest.model_validate(baseline_request))
        baseline_ids = self._event_ids(baseline.model_dump(mode="json"))
        for target in next_times[:100]:
            probe = dict(request_data)
            probe["as_of"] = pd.Timestamp(target).isoformat()
            result = self.analysis.analyze(AnalyzeRequest.model_validate(probe))
            if self._event_ids(result.model_dump(mode="json")) != baseline_ids:
                return target
        return next_times[min(99, len(next_times) - 1)]

    @staticmethod
    def _event_ids(payload: dict[str, Any]) -> set[str]:
        return {item["id"] for item in payload["chan"]["execution"].get("signal_history", [])}

    def _evaluation(self, session: dict[str, Any], final_result: Any) -> dict[str, Any]:
        request = session["request"]
        frame, _ = self.data.load_frame(request["symbol"], request.get("execution_level", "5m"))
        signals = final_result.chan["execution"].get("signal_history", [])
        rows = []
        for signal in signals:
            confirmed_at = signal["lifecycle"].get("confirmed_at")
            if not confirmed_at:
                continue
            future = frame.loc[frame["time"] > pd.Timestamp(confirmed_at)].head(20)
            if future.empty:
                continue
            price = float(signal["price"])
            if "B" in signal["label"]:
                mfe = (float(future["high"].max()) - price) / price
                mae = (float(future["low"].min()) - price) / price
            else:
                mfe = (price - float(future["low"].min())) / price
                mae = (price - float(future["high"].max())) / price
            rows.append({"signal_id": signal["id"], "mfe": round(mfe, 6), "mae": round(mae, 6)})
        return {
            "initial_as_of": session["initial_as_of"],
            "completed_at": session["current_as_of"],
            "signal_outcomes": rows,
            "note": "MFE/MAE仅在Replay完成后生成，未进入实时分析响应。",
        }
