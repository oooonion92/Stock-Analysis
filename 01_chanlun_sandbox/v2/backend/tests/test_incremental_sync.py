from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.data_service import DataService
from app.storage import Storage


def bars(times: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "time": times,
        "open": closes,
        "high": [value + 0.01 for value in closes],
        "low": [value - 0.01 for value in closes],
        "close": closes,
        "volume": [100.0] * len(times),
        "amount": [1000.0] * len(times),
    })


def test_sync_appends_new_bars_without_overwriting_corrected_history(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = DataService(tmp_path / "data", Storage(tmp_path / "runtime" / "test.sqlite3"))
    existing = bars(
        ["2026-07-21 10:00:00", "2026-07-21 10:05:00"],
        [1.0, 1.1],
    )
    incoming = bars(
        ["2026-07-21 10:05:00", "2026-07-21 10:10:00"],
        [3.3, 1.2],
    )
    for level in ("5m", "30m"):
        path = service.period_file("sh588200", level)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing.to_csv(path, index=False)

    requested_rows: list[tuple[int, int]] = []

    def fetch(_symbol: str, scale: int, datalen: int) -> pd.DataFrame:
        requested_rows.append((scale, datalen))
        return incoming.copy()

    monkeypatch.setattr(service, "_fetch_sina_bars", fetch)
    monkeypatch.setattr(service, "fetch_name", lambda _symbol: "科创芯片ETF")

    result = service.sync_symbol("sh588200")

    assert all(item["added_rows"] == 1 for item in result["periods"])
    assert all(item["ignored_overlap_rows"] == 1 for item in result["periods"])
    assert all(datalen < 1970 for _scale, datalen in requested_rows)
    for level in ("5m", "30m"):
        saved = pd.read_csv(service.period_file("sh588200", level))
        assert saved.loc[saved["time"] == "2026-07-21 10:05:00", "close"].item() == 1.1
        assert saved.loc[saved["time"] == "2026-07-21 10:10:00", "close"].item() == 1.2


def test_incremental_request_size_uses_local_watermark() -> None:
    last_time = pd.Timestamp("2026-07-21 15:00:00")
    now = pd.Timestamp("2026-07-22 15:00:00")

    assert DataService._incremental_datalen(last_time, 5, now) == 98
    assert DataService._incremental_datalen(last_time, 30, now) == 18
