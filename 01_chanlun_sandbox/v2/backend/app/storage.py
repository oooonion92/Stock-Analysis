from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    symbol TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    periods_json TEXT NOT NULL DEFAULT '[]',
                    last_synced_at TEXT,
                    data_hash TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS annotations (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_sessions (
                    id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    current_as_of TEXT NOT NULL,
                    initial_as_of TEXT NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_instrument(
        self,
        symbol: str,
        name: str,
        periods: list[str],
        data_hash: str | None = None,
        synced: bool = False,
    ) -> None:
        now = self.now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO instruments(symbol,name,periods_json,last_synced_at,data_hash,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name=CASE WHEN excluded.name <> '' THEN excluded.name ELSE instruments.name END,
                    periods_json=excluded.periods_json,
                    last_synced_at=CASE WHEN excluded.last_synced_at IS NOT NULL THEN excluded.last_synced_at ELSE instruments.last_synced_at END,
                    data_hash=COALESCE(excluded.data_hash,instruments.data_hash),
                    updated_at=excluded.updated_at
                """,
                (symbol, name, json.dumps(periods), now if synced else None, data_hash, now),
            )

    def instrument_metadata(self) -> dict[str, dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM instruments ORDER BY symbol").fetchall()
        return {
            row["symbol"]: {
                "name": row["name"],
                "periods": json.loads(row["periods_json"]),
                "last_synced_at": row["last_synced_at"],
                "data_hash": row["data_hash"],
            }
            for row in rows
        }

    def create_snapshot(self, payload: dict[str, Any], note: str) -> dict[str, Any]:
        snapshot_id = uuid.uuid4().hex
        now = self.now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    snapshot_id,
                    payload["symbol"],
                    payload["as_of"],
                    payload["data_hash"],
                    payload["config_hash"],
                    payload["model_version"],
                    note,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
        return {"id": snapshot_id, "created_at": now, "payload": payload, "note": note}

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "note": row["note"],
            "payload": json.loads(row["payload_json"]),
        }

    def list_snapshots(self, symbol: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id,symbol,as_of,data_hash,config_hash,model_version,note,created_at FROM snapshots"
        params: tuple[Any, ...] = ()
        if symbol:
            sql += " WHERE symbol=?"
            params = (symbol,)
        sql += " ORDER BY created_at DESC"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def create_annotation(self, data: dict[str, Any]) -> dict[str, Any]:
        annotation_id = uuid.uuid4().hex
        now = self.now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO annotations VALUES(?,?,?,?,?,?,?)",
                (
                    annotation_id,
                    data["symbol"],
                    data["as_of"],
                    data["kind"],
                    json.dumps(data["payload"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        return {"id": annotation_id, **data, "created_at": now, "updated_at": now}

    def list_annotations(self, symbol: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM annotations"
        params: tuple[Any, ...] = ()
        if symbol:
            sql += " WHERE symbol=?"
            params = (symbol,)
        sql += " ORDER BY as_of,created_at"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "as_of": row["as_of"],
                "kind": row["kind"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def update_annotation(self, annotation_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        now = self.now()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM annotations WHERE id=?", (annotation_id,)).fetchone()
            if not row:
                return None
            symbol = data.get("symbol", row["symbol"])
            as_of = data.get("as_of", row["as_of"])
            kind = data.get("kind", row["kind"])
            payload = data.get("payload", json.loads(row["payload_json"]))
            conn.execute(
                "UPDATE annotations SET symbol=?,as_of=?,kind=?,payload_json=?,updated_at=? WHERE id=?",
                (symbol, as_of, kind, json.dumps(payload, ensure_ascii=False), now, annotation_id),
            )
        return {
            "id": annotation_id,
            "symbol": symbol,
            "as_of": as_of,
            "kind": kind,
            "payload": payload,
            "created_at": row["created_at"],
            "updated_at": now,
        }

    def delete_annotation(self, annotation_id: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute("DELETE FROM annotations WHERE id=?", (annotation_id,))
        return cursor.rowcount > 0

    def create_replay(self, request: dict[str, Any], initial_as_of: str) -> str:
        session_id = uuid.uuid4().hex
        now = self.now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO replay_sessions VALUES(?,?,?,?,?,?,?)",
                (session_id, json.dumps(request, ensure_ascii=False), initial_as_of, initial_as_of, 0, now, now),
            )
        return session_id

    def get_replay(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM replay_sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["request"] = json.loads(result.pop("request_json"))
        result["completed"] = bool(result["completed"])
        return result

    def update_replay(self, session_id: str, current_as_of: str, completed: bool = False) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE replay_sessions SET current_as_of=?,completed=?,updated_at=? WHERE id=?",
                (current_as_of, int(completed), self.now(), session_id),
            )
