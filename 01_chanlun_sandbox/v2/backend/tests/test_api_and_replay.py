from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def walk_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key.lower())
            keys.update(walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(walk_keys(child))
    return keys


def test_health_stocks_openapi_and_legacy_adapter(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["csv_files"] == 50
    assert health.json()["chan_engine"] == "chan.py"
    assert health.json()["chan_engine_commit"].startswith("429d6ed304")
    stocks = client.get("/api/v2/stocks").json()["stocks"]
    assert any(item["symbol"] == "sz002463" and item["name"] == "沪电股份" for item in stocks)
    assert client.get("/api/openapi.json").status_code == 200
    legacy = client.get("/api/analyze", params={"symbol": "sh000001", "period": "5m"})
    assert legacy.status_code == 200
    assert {"bars", "zs", "signals", "bi_points", "current"}.issubset(legacy.json())


def test_live_response_has_no_forward_performance_fields_and_hides_invalidated(client: TestClient) -> None:
    response = client.post("/api/v2/analyze", json={"symbol": "sz002463"})
    assert response.status_code == 200
    payload = response.json()
    forbidden = {"forward", "mfe", "mae", "future", "future_bars"}
    assert not (walk_keys(payload) & forbidden)
    assert all(item["lifecycle"]["state"] != "invalidated" for item in payload["chan"]["execution"]["signals"])
    assert any(item["lifecycle"]["state"] == "invalidated" for item in payload["chan"]["execution"]["signal_history"])
    assert payload["wyckoff"] == {"status": "removed", "events": [], "features": {"series": {}}}
    assert payload["wave"] == {"status": "removed", "primary": None, "alternate": None, "context": []}
    plan_text = " ".join(str(value) for value in payload["plan"].values())
    assert "供需" not in plan_text
    assert "波浪" not in plan_text


def test_display_period_switch_keeps_both_chan_levels(client: TestClient) -> None:
    five = client.post("/api/v2/analyze", json={"symbol": "sh000001", "display_level": "5m"}).json()
    thirty = client.post("/api/v2/analyze", json={"symbol": "sh000001", "display_level": "30m"}).json()
    assert five["levels"]["display"] == "5m"
    assert thirty["levels"]["display"] == "30m"
    assert len(thirty["bars"]) < len(five["bars"])
    assert thirty["chan"]["execution"]["pivots"]
    assert thirty["chan"]["decision"]["pivots"]
    assert thirty["chan"]["higher"]["level"] == "1d"
    assert five["fusion"]["structure"] == five["chan"]["execution"]["current"]["state"]
    assert thirty["fusion"]["structure"] == thirty["chan"]["decision"]["current"]["state"]
    assert "segments" in thirty["chan"]["decision"]
    assert len(thirty["indicators"]["macd"]["dif"]) == len(thirty["bars"])
    assert thirty["radar"]["version"] == "chanpy-radar-1.0"
    for layer in (thirty["radar"]["execution"], thirty["radar"]["decision"], thirty["radar"]["higher"]):
        assert set(layer) >= {"pivots", "swings", "zones", "events", "current", "summary"}
        assert all(item["id"].startswith("chanpy-") for item in layer["pivots"])


def test_replay_never_returns_bars_after_current_clock(client: TestClient) -> None:
    analysis = {
        "symbol": "sz002463",
        "start": "2026-05-18T00:00:00",
        "profile": "balanced",
    }
    created = client.post(
        "/api/v2/replay",
        json={"analysis": analysis, "initial_as_of": "2026-05-20T13:45:00"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert max(bar["time"] for bar in payload["analysis"]["bars"]) <= payload["current_as_of"]
    advanced = client.post(
        f"/api/v2/replay/{payload['session_id']}/advance",
        json={"mode": "bars", "count": 5},
    ).json()
    assert max(bar["time"] for bar in advanced["analysis"]["bars"]) <= advanced["current_as_of"]
    assert not ({"forward", "mfe", "mae", "future"} & walk_keys(advanced["analysis"]))


def test_snapshot_payload_is_immutable(client: TestClient) -> None:
    request = {
        "analysis": {"symbol": "sz002463", "as_of": "2026-05-20T13:45:00"},
        "note": "candidate evidence",
    }
    created = client.post("/api/v2/snapshots", json=request).json()
    snapshot_id = created["id"]
    original = created["payload"]
    client.post("/api/v2/analyze", json={"symbol": "sz002463", "as_of": "2026-07-14T15:00:00"})
    fetched = client.get(f"/api/v2/snapshots/{snapshot_id}").json()["payload"]
    assert fetched == original
    assert fetched["visible_bar_end"] <= fetched["as_of"]


def test_manual_gold_annotation_crud(client: TestClient) -> None:
    created = client.post(
        "/api/v2/annotations",
        json={
            "symbol": "SH000001",
            "as_of": "2026-07-14T10:35:00",
            "kind": "signal",
            "payload": {
                "gold_schema_version": "1.0",
                "human_status": "confirmed",
                "level": "5m",
                "signal_type": "1B",
                "event_at": "2026-07-14T09:55:00",
                "confirmed_at": "2026-07-14T10:35:00",
                "event_price": 3868.0,
                "data_hash": "gold-test",
            },
        },
    )
    assert created.status_code == 200
    annotation = created.json()
    assert annotation["symbol"] == "sh000001"
    assert annotation["kind"] == "signal"

    listed = client.get("/api/v2/annotations", params={"symbol": "sh000001"})
    assert listed.status_code == 200
    assert any(item["id"] == annotation["id"] for item in listed.json()["annotations"])

    updated = client.patch(
        f"/api/v2/annotations/{annotation['id']}",
        json={"payload": {**annotation["payload"], "note": "manual review passed"}},
    )
    assert updated.status_code == 200
    assert updated.json()["payload"]["note"] == "manual review passed"

    deleted = client.delete(f"/api/v2/annotations/{annotation['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
