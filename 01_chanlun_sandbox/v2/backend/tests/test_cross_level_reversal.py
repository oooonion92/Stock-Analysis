from __future__ import annotations

from fastapi.testclient import TestClient


SOURCE_EVENT = "2026-05-19T10:20:00"


def event_at(payload: dict, timestamp: str) -> dict:
    return next(
        item
        for item in payload["cross_level"]["events"]
        if item["lifecycle"]["event_at"] == timestamp
    )


def analyze_at(client: TestClient, timestamp: str) -> dict:
    response = client.post(
        "/api/v2/analyze",
        json={
            "symbol": "sh000001",
            "as_of": timestamp,
            "include_invalidated": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_cross_level_event_advances_without_future_data(client: TestClient) -> None:
    candidate = event_at(analyze_at(client, "2026-05-19T10:30:00"), SOURCE_EVENT)
    triggered = event_at(analyze_at(client, "2026-05-19T10:40:00"), SOURCE_EVENT)
    confirmed = event_at(analyze_at(client, "2026-05-19T11:00:00"), SOURCE_EVENT)

    assert candidate["break_boundary"] == 4117.435
    assert candidate["lifecycle"]["state"] == "candidate"
    assert candidate["lifecycle"]["triggered_at"] is None
    assert candidate["lifecycle"]["confirmed_at"] is None

    assert triggered["id"] == candidate["id"]
    assert triggered["break_boundary"] == candidate["break_boundary"]
    assert triggered["lifecycle"]["state"] == "triggered"
    assert triggered["lifecycle"]["triggered_at"] == "2026-05-19T10:35:00"
    assert triggered["lifecycle"]["confirmed_at"] is None

    assert confirmed["id"] == candidate["id"]
    assert confirmed["lifecycle"]["state"] == "confirmed"
    assert confirmed["lifecycle"]["confirmed_at"] == "2026-05-19T11:00:00"
    assert confirmed["evidence"]["decision_context"]["direction"] == "down"


def test_cross_level_confirmation_can_later_invalidate(client: TestClient) -> None:
    payload = analyze_at(client, "2026-05-21T14:30:00")
    event = event_at(payload, SOURCE_EVENT)

    assert event["lifecycle"]["state"] == "invalidated"
    assert event["lifecycle"]["confirmed_at"] == "2026-05-19T11:00:00"
    assert event["lifecycle"]["invalidated_at"] == "2026-05-21T14:30:00"


def test_internal_rebounds_do_not_become_cross_level_confirmations(client: TestClient) -> None:
    payload = client.post(
        "/api/v2/analyze",
        json={"symbol": "sh000001", "include_invalidated": True},
    ).json()
    events = payload["cross_level"]["events"]
    cases = {
        "2026-05-28T13:15:00": 4199.527,
        "2026-06-02T10:10:00": 4112.955,
    }

    for timestamp, boundary in cases.items():
        event = event_at(payload, timestamp)
        assert event["break_boundary"] == boundary
        assert event["lifecycle"]["triggered_at"] is None
        assert event["lifecycle"]["confirmed_at"] is None
        assert event["lifecycle"]["state"] == "invalidated"


def test_display_start_does_not_change_cross_level_history(client: TestClient) -> None:
    common = {
        "symbol": "sh000001",
        "display_level": "30m",
        "end": "2026-07-17T23:59:59",
        "include_invalidated": True,
    }
    wide = client.post(
        "/api/v2/analyze",
        json={**common, "start": "2026-05-01T00:00:00"},
    ).json()
    narrow = client.post(
        "/api/v2/analyze",
        json={**common, "start": "2026-06-30T00:00:00"},
    ).json()

    assert narrow["cross_level"] == wide["cross_level"]
