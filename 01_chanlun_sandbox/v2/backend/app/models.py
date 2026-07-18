from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LifecycleState(str, Enum):
    candidate = "candidate"
    confirmed = "confirmed"
    risk_downgraded = "risk_downgraded"
    invalidated = "invalidated"
    expired = "expired"


class MarketBar(StrictModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    vwap: float | None = None


class Pivot(StrictModel):
    level: str
    kind: Literal["top", "bottom"]
    event_at: datetime
    confirmed_at: datetime
    price: float


class Stroke(StrictModel):
    level: str
    start_at: datetime
    end_at: datetime
    confirmed_at: datetime
    direction: Literal["up", "down"]
    start_price: float
    end_price: float
    stroke_count: int = 1
    macd_area: float = 0.0
    volume: float = 0.0


class Segment(StrictModel):
    level: str
    start_at: datetime
    end_at: datetime
    confirmed_at: datetime
    direction: Literal["up", "down"]
    start_price: float
    end_price: float
    stroke_count: int
    macd_area: float = 0.0
    volume: float = 0.0


class Center(StrictModel):
    id: str
    level: str
    start_at: datetime
    end_at: datetime
    zd: float
    zg: float
    dd: float | None = None
    gg: float | None = None
    state: str
    stroke_count: int
    component_type: Literal["stroke", "segment", "center"] = "segment"
    component_count: int = 0
    extension_count: int = 0
    promoted_from: list[str] = Field(default_factory=list)


class SignalLifecycle(StrictModel):
    state: LifecycleState
    event_at: datetime
    detected_at: datetime
    confirmed_at: datetime | None = None
    invalidated_at: datetime | None = None
    expired_at: datetime | None = None


class ChanSignal(StrictModel):
    id: str
    level: str
    label: Literal["1B", "2B", "3B", "1S", "2S", "3S"]
    price: float
    confidence: float = Field(ge=0, le=1)
    divergence_class: str
    structure_guard: float
    risk_guard: float
    lifecycle: SignalLifecycle
    evidence: dict[str, Any]


class FusionState(StrictModel):
    grade: Literal["A", "B", "C", "D"]
    structure: str
    supply_demand: str
    path: str
    conflicts: list[str]


class TradePlan(StrictModel):
    trigger: str
    invalidation: str
    action: str
    forbidden: str
    next_observation: str
    position_tier: Literal["normal", "reduced", "research", "none"]


class AnalyzeRequest(StrictModel):
    symbol: str
    decision_level: Literal["30m"] = "30m"
    execution_level: Literal["5m"] = "5m"
    display_level: Literal["5m", "30m"] = "5m"
    start: datetime | None = None
    end: datetime | None = None
    as_of: datetime | None = None
    profile: str = "balanced"
    benchmark: str | None = "sh000001"
    include_invalidated: bool = False
    research_overrides: dict[str, float] | None = None

    @field_validator("symbol", "benchmark")
    @classmethod
    def normalize_symbols(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value


class SyncRequest(StrictModel):
    symbol: str


class AnalysisResponse(BaseModel):
    schema_version: str
    model_version: str
    config_hash: str
    data_hash: str
    as_of: datetime
    visible_bar_end: datetime
    symbol: str
    stock_name: str
    levels: dict[str, str]
    data_quality: dict[str, Any]
    bars: list[MarketBar]
    indicators: dict[str, Any]
    radar: dict[str, Any]
    chan: dict[str, Any]
    wyckoff: dict[str, Any]
    wave: dict[str, Any]
    fusion: FusionState
    plan: TradePlan
    warnings: list[str] = []


class ReplayCreateRequest(StrictModel):
    analysis: AnalyzeRequest
    initial_as_of: datetime


class ReplayAdvanceRequest(StrictModel):
    mode: Literal["bars", "next_event", "session_end"] = "bars"
    count: int = Field(default=1, ge=1, le=100)


class SnapshotCreateRequest(StrictModel):
    analysis: AnalyzeRequest
    note: str = ""


class AnnotationRequest(StrictModel):
    symbol: str
    as_of: datetime
    kind: Literal["pivot", "stroke", "segment", "center", "signal", "wave", "range", "note"]
    payload: dict[str, Any]

    @field_validator("symbol")
    @classmethod
    def normalize_annotation_symbol(cls, value: str) -> str:
        return value.strip().lower()


class ExportRequest(StrictModel):
    analysis: AnalyzeRequest
