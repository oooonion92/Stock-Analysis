from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import AppConfig
from .data_service import DataQualityError, DataService
from .models import (
    AnalyzeRequest,
    AnnotationRequest,
    ExportRequest,
    ReplayAdvanceRequest,
    ReplayCreateRequest,
    SnapshotCreateRequest,
    SyncRequest,
)
from .services.analysis import AnalysisService
from .services.replay import ReplayService
from .storage import Storage
from .engines.chanpy_engine import CHANPY_COMMIT


def create_app(config: AppConfig | None = None) -> FastAPI:
    settings = config or AppConfig()
    settings.ensure_runtime()
    storage = Storage(settings.database_path)
    data = DataService(settings.data_dir, storage)
    analysis = AnalysisService(settings, data)
    replay = ReplayService(storage, data, analysis)

    app = FastAPI(
        title="Chanlun Sandbox V2",
        version=settings.model_version,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = settings
    app.state.storage = storage
    app.state.data = data
    app.state.analysis = analysis
    app.state.replay = replay

    @app.exception_handler(DataQualityError)
    async def data_quality_error(_request: Any, exc: DataQualityError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": str(exc), "kind": "data_quality"})

    @app.exception_handler(FileNotFoundError)
    async def missing_file_error(_request: Any, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": str(exc), "kind": "missing_data"})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        csv_files = list(settings.data_dir.glob("*_MaxAvailable.csv")) if settings.data_dir.exists() else []
        latest = max((path.stat().st_mtime for path in csv_files), default=None)
        return {
            "status": "ok" if settings.data_dir.exists() else "degraded",
            "schema_version": settings.schema_version,
            "model_version": settings.model_version,
            "chan_engine": "chan.py",
            "chan_engine_commit": CHANPY_COMMIT,
            "data_dir": str(settings.data_dir),
            "data_dir_exists": settings.data_dir.exists(),
            "data_dir_writable": os.access(settings.data_dir, os.W_OK) if settings.data_dir.exists() else False,
            "csv_files": len(csv_files),
            "latest_file_epoch": latest,
            "database": str(settings.database_path),
            "frontend_ready": (settings.frontend_dist / "index.html").exists(),
            "python": sys.version.split()[0],
        }

    @app.get("/api/v2/stocks")
    def stocks() -> dict[str, Any]:
        return {"stocks": data.list_stocks()}

    @app.post("/api/v2/sync")
    def sync(request: SyncRequest) -> dict[str, Any]:
        try:
            return data.sync_symbol(request.symbol)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/v2/analyze")
    def analyze(request: AnalyzeRequest) -> Any:
        try:
            return analysis.analyze(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v2/replay")
    def create_replay(request: ReplayCreateRequest) -> Any:
        return replay.create(request)

    @app.get("/api/v2/replay/{session_id}")
    def get_replay(session_id: str) -> Any:
        result = replay.get(session_id)
        if not result:
            raise HTTPException(status_code=404, detail="replay session not found")
        return result

    @app.post("/api/v2/replay/{session_id}/advance")
    def advance_replay(session_id: str, request: ReplayAdvanceRequest) -> Any:
        result = replay.advance(session_id, request)
        if not result:
            raise HTTPException(status_code=404, detail="replay session not found")
        return result

    @app.post("/api/v2/snapshots")
    def create_snapshot(request: SnapshotCreateRequest) -> Any:
        result = analysis.analyze(request.analysis).model_dump(mode="json")
        return storage.create_snapshot(result, request.note)

    @app.get("/api/v2/snapshots")
    def list_snapshots(symbol: str | None = None) -> Any:
        return {"snapshots": storage.list_snapshots(symbol)}

    @app.get("/api/v2/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: str) -> Any:
        result = storage.get_snapshot(snapshot_id)
        if not result:
            raise HTTPException(status_code=404, detail="snapshot not found")
        return result

    @app.post("/api/v2/annotations")
    def create_annotation(request: AnnotationRequest) -> Any:
        return storage.create_annotation(request.model_dump(mode="json"))

    @app.get("/api/v2/annotations")
    def list_annotations(symbol: str | None = None) -> Any:
        return {"annotations": storage.list_annotations(symbol)}

    @app.patch("/api/v2/annotations/{annotation_id}")
    def update_annotation(annotation_id: str, payload: dict[str, Any]) -> Any:
        result = storage.update_annotation(annotation_id, payload)
        if not result:
            raise HTTPException(status_code=404, detail="annotation not found")
        return result

    @app.delete("/api/v2/annotations/{annotation_id}")
    def delete_annotation(annotation_id: str) -> Any:
        if not storage.delete_annotation(annotation_id):
            raise HTTPException(status_code=404, detail="annotation not found")
        return {"deleted": True}

    @app.post("/api/v2/export")
    def export(request: ExportRequest) -> Any:
        return analysis.export(request.analysis)

    # Compatibility adapters live only on V2. The V1 process and files stay untouched.
    @app.get("/api/stocks")
    def legacy_stocks() -> dict[str, Any]:
        return {"stocks": data.list_stocks()}

    @app.get("/api/fetch")
    def legacy_fetch(symbol: str) -> dict[str, Any]:
        return data.sync_symbol(symbol)

    @app.get("/api/analyze")
    def legacy_analyze(
        symbol: str,
        period: str = Query(default="5m", pattern="^(5m|30m)$"),
        start: str | None = None,
        sensitivity: str = "balanced",
    ) -> dict[str, Any]:
        request = AnalyzeRequest(
            symbol=symbol,
            execution_level="5m",
            decision_level="30m",
            display_level=period,
            start=start,
            profile=sensitivity,
        )
        payload = analysis.analyze(request).model_dump(mode="json")
        layer_name = "execution" if period == "5m" else "decision"
        layer = payload["chan"][layer_name]
        signals = [
            {
                "id": item["id"],
                "time": item["lifecycle"]["event_at"],
                "price": item["price"],
                "label": item["label"],
                "confidence": item["confidence"],
                "evidence": item["evidence"],
                "lifecycle": item["lifecycle"],
                "level": period,
            }
            for item in layer["signals"]
        ]
        return {
            "symbol": payload["symbol"],
            "stock_name": payload["stock_name"],
            "period": period,
            "version": payload["model_version"],
            "bars": payload["bars"],
            "zs": [
                {"start": item["start_at"], "end": item["end_at"], "ZD": item["zd"], "ZG": item["zg"], "bi_count": item["stroke_count"]}
                for item in layer["centers"]
            ],
            "signals": signals,
            "candidates": [item for item in signals if item["lifecycle"]["state"] == "candidate"],
            "bi_points": [{"time": item["event_at"], "value": item["price"]} for item in layer["pivots"]],
            "layers": [],
            "current": layer["current"],
            "summary": layer["summary"],
        }

    @app.get("/", include_in_schema=False)
    def root() -> Any:
        index = settings.frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content={"status": "frontend_not_built", "hint": "run v2/start_v2.ps1"},
        )

    assets = settings.frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    return app


app = create_app()
