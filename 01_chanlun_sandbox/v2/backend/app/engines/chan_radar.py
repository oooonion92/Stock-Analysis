from __future__ import annotations

import copy
from typing import Any


RADAR_VERSION = "chanpy-radar-1.0"


class ChanRadarAdapter:
    """Keep the radar API while using chan.py as the single structure source."""

    def analyze(self, chan: dict[str, Any], level: str) -> dict[str, Any]:
        pivots = [copy.deepcopy(item) for item in chan.get("pivots", []) if item.get("is_sure", True)]
        strokes = [copy.deepcopy(item) for item in chan.get("strokes", []) if item.get("is_sure", True)]
        centers = [copy.deepcopy(item) for item in chan.get("centers", [])]
        current = chan.get("current", {})
        zones = [self._zone(item, current.get("state")) for item in centers]
        events = [self._event(item) for item in chan.get("signals", []) if item["lifecycle"]["state"] == "confirmed"]
        radar_current = {
            "level": level,
            "state": current.get("state", "insufficient_structure"),
            "price": current.get("price"),
            "zone": zones[-1] if zones else None,
            "last_pivot": pivots[-1] if pivots else None,
            "last_swing": strokes[-1] if strokes else None,
            "last_event": events[-1] if events else None,
            "risk_line": current.get("risk_line"),
            "observation": current.get("observation", "等待新的确认结构。"),
        }
        return {
            "version": RADAR_VERSION,
            "level": level,
            "pivots": pivots,
            "swings": strokes,
            "zones": zones,
            "events": events,
            "current": radar_current,
            "summary": {
                "confirmed_pivots": len(pivots),
                "confirmed_swings": len(strokes),
                "balance_zones": len(zones),
                "confirmed_events": len(events),
            },
        }

    @staticmethod
    def _zone(center: dict[str, Any], market_state: str | None) -> dict[str, Any]:
        return {
            "id": center["id"],
            "level": center["level"],
            "start_at": center["start_at"],
            "formed_at": center["end_at"],
            "end_at": center["end_at"],
            "departure_scan_at": center["end_at"],
            "zd": center["zd"],
            "zg": center["zg"],
            "low": center.get("dd", center["zd"]),
            "high": center.get("gg", center["zg"]),
            "component_count": center.get("component_count", center.get("stroke_count", 0)),
            "extension_count": center.get("extension_count", 0),
            "state": "completed" if center.get("state") == "completed" else "active",
            "market_state": market_state or "center_balance",
        }

    @staticmethod
    def _event(signal: dict[str, Any]) -> dict[str, Any]:
        lifecycle = signal["lifecycle"]
        label = signal["label"]
        event_type = {
            "1B": "first_buy",
            "2B": "second_buy",
            "3B": "third_buy",
            "1S": "first_sell",
            "2S": "second_sell",
            "3S": "third_sell",
        }.get(label, label)
        return {
            "id": signal["id"],
            "level": signal["level"],
            "type": event_type,
            "zone_id": signal["evidence"].get("center", {}).get("id") if signal["evidence"].get("center") else "",
            "event_at": lifecycle["event_at"],
            "confirmed_at": lifecycle["confirmed_at"] or lifecycle["detected_at"],
            "price": signal["price"],
            "boundary": signal["structure_guard"],
            "risk_line": signal["risk_guard"],
            "status": "confirmed",
            "evidence": {
                "volume_status": "unavailable",
                "macd_status": "supportive" if signal["divergence_class"].endswith("divergence") else "neutral",
                "relative_volume": signal["evidence"].get("ratios", {}).get("volume_average"),
                "histogram": None,
            },
        }
