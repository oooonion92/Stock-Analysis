from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from app.config import AppConfig
from app.engines.chanpy_engine import CHANPY_COMMIT
from app.main import create_app


def signal_history(payload: dict, layer: str = "execution") -> list[dict]:
    return payload["chan"][layer]["signal_history"]


def test_sh000001_full_history_matches_chanpy_golden_structure(client: TestClient) -> None:
    response = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    )
    assert response.status_code == 200
    payload = response.json()
    execution = payload["chan"]["execution"]
    decision = payload["chan"]["decision"]

    assert execution["engine"] == "chan.py"
    assert execution["engine_commit"] == CHANPY_COMMIT
    assert execution["summary"] == {
        "bars": 5328,
        "pivots": 276,
        "strokes": 275,
        "confirmed_strokes": 274,
        "segments": 45,
        "confirmed_segments": 42,
        "higher_segments": 8,
        "centers": 30,
        "segment_centers": 6,
        "signals": 5,
        "signal_history": 72,
        "strict_first_signals": 13,
    }
    assert decision["summary"]["strokes"] == 140
    assert decision["summary"]["segments"] == 23
    assert decision["summary"]["centers"] == 16
    assert decision["summary"]["signals"] == 8
    assert decision["summary"]["signal_history"] == 39
    assert decision["summary"]["strict_first_signals"] == 6

    for layer in (execution, decision):
        raw_points = layer["signal_history"]
        point_keys = {
            (
                item["evidence"]["scope"],
                item["lifecycle"]["event_at"],
                item["price"],
                tuple(item["evidence"]["native_types"]),
            )
            for item in raw_points
        }
        assert len(point_keys) == len(raw_points)
        assert all(item["display_label"].startswith(("笔B", "笔S", "段B", "段S")) for item in raw_points)

    assert any("," in item["display_label"] for item in execution["signal_history"])


def test_strict_divergence_rejects_single_metric_weakening(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    ).json()
    candidate = next(
        item
        for item in signal_history(payload)
        if item["label"] == "1B"
        and item["lifecycle"]["event_at"] == "2026-06-17T13:10:00"
    )
    audit = candidate["evidence"]["divergence_audit"]
    ratios = candidate["evidence"]["ratios"]

    assert candidate["lifecycle"]["state"] == "candidate"
    assert candidate["lifecycle"]["confirmed_at"] is None
    assert candidate["id"] not in {item["id"] for item in payload["chan"]["execution"]["signals"]}
    assert audit["status"] == "insufficient"
    assert audit["price_extension"] is True
    assert audit["momentum_votes"] == 1
    assert audit["required_votes"] == 2
    assert ratios["macd_area"] > 4.6
    assert ratios["macd_peak"] > 1.54
    assert ratios["dif_extreme"] < 0.75


def test_second_buy_inherits_unconfirmed_first_buy_state(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    ).json()
    history = signal_history(payload)
    first_buy = next(
        item for item in history
        if item["display_label"] == "笔B1p"
        and item["lifecycle"]["event_at"] == "2026-07-14T11:25:00"
    )
    second_buy = next(
        item for item in history
        if item["display_label"] == "笔B2"
        and item["lifecycle"]["event_at"] == "2026-07-14T13:55:00"
    )

    assert first_buy["lifecycle"]["state"] == "candidate"
    assert second_buy["lifecycle"]["state"] == "candidate"
    assert second_buy["lifecycle"]["confirmed_at"] is None
    assert second_buy["evidence"]["dependency"]["parent_signal_id"] == first_buy["id"]
    assert second_buy["evidence"]["dependency"]["status"] == "pending"
    assert second_buy["id"] not in {item["id"] for item in payload["chan"]["execution"]["signals"]}


def test_confirmed_buy_chains_retire_after_visible_guard_break(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    ).json()
    history = signal_history(payload)
    cases = {
        "2026-05-28T13:15:00": "2026-06-01T11:10:00",
        "2026-05-28T14:15:00": "2026-06-01T11:10:00",
        "2026-06-02T10:10:00": "2026-06-05T14:25:00",
        "2026-06-03T09:35:00": "2026-06-05T14:25:00",
    }
    retired = {
        item["lifecycle"]["event_at"]: item
        for item in history
        if item["lifecycle"]["event_at"] in cases
    }
    assert retired.keys() == cases.keys()
    for event_at, invalidated_at in cases.items():
        signal = retired[event_at]
        assert signal["lifecycle"]["state"] == "invalidated"
        assert signal["lifecycle"]["confirmed_at"] is not None
        assert signal["lifecycle"]["invalidated_at"] == invalidated_at
        assert signal["id"] not in {item["id"] for item in payload["chan"]["execution"]["signals"]}

    first_buy = retired["2026-06-02T10:10:00"]
    second_buy = retired["2026-06-03T09:35:00"]
    assert second_buy["risk_guard"] == first_buy["risk_guard"]
    assert second_buy["evidence"]["dependency"]["parent_state"] == "invalidated"


def test_buy_chain_is_still_confirmed_before_future_guard_break(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={
            "symbol": "sh000001",
            "as_of": "2026-06-03T15:00:00",
            "include_invalidated": True,
        },
    ).json()
    history = signal_history(payload)
    first_buy = next(
        item for item in history
        if item["lifecycle"]["event_at"] == "2026-06-02T10:10:00"
    )
    second_buy = next(
        item for item in history
        if item["lifecycle"]["event_at"] == "2026-06-03T09:35:00"
    )
    assert first_buy["lifecycle"]["state"] == "confirmed"
    assert second_buy["lifecycle"]["state"] == "confirmed"
    assert first_buy["lifecycle"]["invalidated_at"] is None
    assert second_buy["lifecycle"]["invalidated_at"] is None


def test_segment_bs_points_remain_separate_from_actual_parent_level(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    ).json()
    execution = signal_history(payload, "execution")
    decision = signal_history(payload, "decision")

    segment_points = [item for item in execution if item["evidence"]["scope"] == "segment"]
    parent_points = [item for item in decision if item["evidence"]["scope"] == "stroke"]
    assert segment_points
    assert parent_points
    assert all(item["level"] == "5m段" for item in segment_points)
    assert all(item["level"] == "30m" for item in parent_points)
    assert {item["id"] for item in segment_points}.isdisjoint(item["id"] for item in parent_points)


def test_third_buy_exposes_center_departure_and_retrace_evidence(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sz002384", "display_level": "30m", "include_invalidated": True},
    ).json()
    third_buy = next(
        item for item in signal_history(payload, "decision")
        if item["label"] == "3B"
        and item["lifecycle"]["event_at"] == "2026-04-20T14:00:00"
    )
    evidence = third_buy["evidence"]
    structure = evidence["third_structure"]

    assert third_buy["lifecycle"]["confirmed_at"] == "2026-04-20T14:30:00"
    assert evidence["comparison_kind"] == "center_non_return"
    assert evidence["ratios"] == {}
    assert evidence["center"]["start_at"] == "2026-03-18T14:00:00"
    assert evidence["center"]["end_at"] == "2026-03-25T10:00:00"
    assert evidence["center"]["zg"] == 115.01
    assert evidence["reference"]["startTime"] == "2026-04-02T14:30:00"
    assert evidence["reference"]["endTime"] == "2026-04-20T10:00:00"
    assert evidence["reference"]["startValue"] == 104.8
    assert evidence["reference"]["endValue"] == 168.2
    assert structure["departure"] == evidence["reference"]
    assert structure["retrace"] == evidence["test"]
    assert structure["center_boundary_name"] == "ZG"
    assert structure["center_boundary"] == 115.01
    assert structure["retrace_extreme"] == 155.7
    assert structure["holds_center"] is True
    assert round(structure["clearance"], 2) == 40.69


def test_as_of_analysis_matches_physically_truncated_csv(client: TestClient, tmp_path: Path) -> None:
    cutoff = pd.Timestamp("2026-05-20 13:45:00")
    full = client.post(
        "/api/v2/analyze",
        json={"symbol": "sz002463", "as_of": cutoff.isoformat(), "include_invalidated": True},
    ).json()
    source = Path(r"D:\OneDrive\Stock\details")
    truncated = tmp_path / "details"
    truncated.mkdir()
    for period in ("5Min", "30Min"):
        name = f"sz002463_{period}_MaxAvailable.csv"
        frame = pd.read_csv(source / name)
        frame["time"] = pd.to_datetime(frame["time"])
        frame.loc[frame["time"] <= cutoff].to_csv(truncated / name, index=False)
    config = AppConfig(data_dir=truncated, runtime_dir=tmp_path / "runtime-truncated")
    with TestClient(create_app(config)) as truncated_client:
        prefix = truncated_client.post(
            "/api/v2/analyze",
            json={"symbol": "sz002463", "benchmark": None, "include_invalidated": True},
        ).json()
    full_ids = [(item["id"], item["lifecycle"]) for item in signal_history(full)]
    prefix_ids = [(item["id"], item["lifecycle"]) for item in signal_history(prefix)]
    assert prefix_ids == full_ids


def test_display_start_does_not_restart_chan_structure(client: TestClient) -> None:
    common = {
        "symbol": "sz002463",
        "display_level": "30m",
        "end": "2026-07-17T23:59:59",
        "include_invalidated": True,
    }
    wide = client.post(
        "/api/v2/analyze",
        json={**common, "start": "2026-06-01T00:00:00"},
    ).json()
    narrow = client.post(
        "/api/v2/analyze",
        json={**common, "start": "2026-06-30T00:00:00"},
    ).json()

    assert wide["bars"][0]["time"] < narrow["bars"][0]["time"]
    assert wide["chan"]["decision"]["summary"] == narrow["chan"]["decision"]["summary"]

    cutoff = pd.Timestamp("2026-06-30T00:00:00")
    wide_strokes = [
        item for item in wide["chan"]["decision"]["strokes"]
        if pd.Timestamp(item["end_at"]) >= cutoff
    ]
    assert narrow["chan"]["decision"]["strokes"] == wide_strokes

    wide_signals = [
        item for item in wide["chan"]["decision"]["signal_history"]
        if pd.Timestamp(item["lifecycle"]["event_at"]) >= cutoff
    ]
    narrow_signals = [
        item for item in narrow["chan"]["decision"]["signal_history"]
        if pd.Timestamp(item["lifecycle"]["event_at"]) >= cutoff
    ]
    assert narrow_signals == wide_signals
