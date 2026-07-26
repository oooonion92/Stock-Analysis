from __future__ import annotations

from typing import Any

from ..models import FusionState, TradePlan


class FusionEngine:
    STATE_LABELS = {
        "insufficient_structure": "结构不足",
        "no_center": "尚无中枢",
        "trend_up": "向上走势",
        "trend_down": "向下走势",
        "center_balance": "中枢震荡",
        "balance": "平衡区内",
        "up_leave": "向上离开中枢",
        "down_leave": "向下离开中枢",
        "up_leave_confirmed": "向上离开已确认",
        "down_leave_confirmed": "向下离开已确认",
    }

    def analyze(
        self,
        execution_chan: dict[str, Any],
        decision_chan: dict[str, Any],
    ) -> tuple[FusionState, TradePlan]:
        signals = execution_chan.get("signals") or []
        active = [item for item in signals if item["lifecycle"]["state"] in {"candidate", "confirmed", "risk_downgraded"}]
        latest = active[-1] if active else None
        confirmed_chan = latest is not None and latest["lifecycle"]["state"] == "confirmed"
        conflicts: list[str] = []
        decision_state = (decision_chan.get("current") or {}).get("state", "no_center")
        if latest and "B" in latest["label"] and decision_state.startswith("down_leave"):
            conflicts.append("higher_level_down_leave")
        if latest and "S" in latest["label"] and decision_state.startswith("up_leave"):
            conflicts.append("higher_level_up_leave")
        if confirmed_chan and not conflicts:
            grade = "B"
        elif latest and latest["lifecycle"]["state"] in {"candidate", "confirmed"}:
            grade = "C"
        else:
            grade = "D"
        fusion = FusionState(
            grade=grade,
            structure=(execution_chan.get("current") or {}).get("state", "no_center"),
            supply_demand="removed",
            path="removed",
            conflicts=conflicts,
        )
        plan = self._plan(grade, latest, decision_state)
        return fusion, plan

    @staticmethod
    def _plan(grade: str, signal: dict[str, Any] | None, decision_state: str) -> TradePlan:
        if not signal or grade == "D":
            return TradePlan(
                trigger="等待新的已确认结构信号",
                invalidation="当前无可执行结构",
                action="保持观察",
                forbidden="禁止在结构未确认时追价",
                next_observation="下一处分型、中枢离开或回抽确认",
                position_tier="none",
            )
        buy = "B" in signal["label"]
        guard = signal["structure_guard"]
        guard_action = "跌破" if buy else "升破"
        if grade == "B":
            if buy:
                action = "等待向上延续确认，回撤守住结构保护线后再分段执行"
                position = "normal"
            else:
                action = "降低风险，等待反抽确认后再处理"
                position = "reduced"
        else:
            action = "保持观察，等待候选结构确认"
            position = "research"
        if buy:
            trigger = "价格向上突破确认端点，且回撤不跌破结构保护线"
            next_observation = "突破后回撤能否守住结构保护线"
        else:
            trigger = "价格向下跌破确认端点，且反抽不升破结构保护线"
            next_observation = "跌破后反抽是否受制于结构保护线"
        context_label = FusionEngine.STATE_LABELS.get(decision_state, "方向未明确")
        return TradePlan(
            trigger=trigger,
            invalidation=f"价格有效{guard_action}结构保护线 {guard:.3f}",
            action=action,
            forbidden=f"上级别处于{context_label}时，禁止在没有新确认的情况下追价",
            next_observation=next_observation,
            position_tier=position,
        )
