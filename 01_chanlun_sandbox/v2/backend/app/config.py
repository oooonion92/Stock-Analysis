from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[1]
V2_DIR = BACKEND_DIR.parent


@dataclass(frozen=True)
class AnalysisProfile:
    quantum_buffer: float
    momentum_threshold: float
    dif_peak_threshold: float
    structure_weak_push_max: float
    third_point_hold_ratio: float
    third_point_break_ratio: float
    test_volume_ratio_max: float = 0.75
    sos_spread_z_min: float = 0.8


PROFILES: dict[str, AnalysisProfile] = {
    "production": AnalysisProfile(0.0005, 0.70, 0.95, 1.35, 1.0005, 1.0005),
    "balanced": AnalysisProfile(0.0008, 0.76, 1.00, 1.45, 1.0000, 1.0000),
    "research": AnalysisProfile(0.0012, 0.84, 1.08, 1.60, 0.9990, 0.9990),
}

LEGACY_PROFILE_MAP = {
    "conservative": "production",
    "balanced": "balanced",
    "aggressive": "research",
}


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CHANLUN_DATA_DIR", r"D:\OneDrive\Stock\details")
        )
    )
    runtime_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CHANLUN_V2_RUNTIME_DIR", str(V2_DIR / "runtime"))
        )
    )
    frontend_dist: Path = field(default_factory=lambda: V2_DIR / "frontend" / "dist")
    host: str = "127.0.0.1"
    port: int = 8766
    default_decision_level: str = "30m"
    default_execution_level: str = "5m"
    default_profile: str = "balanced"
    default_benchmark: str = "sh000001"
    schema_version: str = "2.0"
    model_version: str = "chan-logic-v1.0.1"
    visible_trading_days: int = 30

    @property
    def database_path(self) -> Path:
        return self.runtime_dir / "sandbox_v2.sqlite3"

    @property
    def export_dir(self) -> Path:
        return self.runtime_dir / "exports"

    def ensure_runtime(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def config_hash(self, profile: str, overrides: dict[str, Any] | None = None) -> str:
        normalized = normalize_profile(profile)
        payload = {
            "app": {
                "decision": self.default_decision_level,
                "execution": self.default_execution_level,
                "benchmark": self.default_benchmark,
                "chan_engine": "chan.py@429d6ed304",
                "strict_divergence_ratio": 0.85,
                "strict_divergence_votes": 2,
            },
            "profile": normalized,
            "values": asdict(PROFILES[normalized]),
            "overrides": overrides or {},
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


def normalize_profile(profile: str | None) -> str:
    key = (profile or "balanced").strip().lower()
    key = LEGACY_PROFILE_MAP.get(key, key)
    if key not in PROFILES:
        raise ValueError(f"unknown analysis profile: {profile}")
    return key


def profile_values(profile: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    values = asdict(PROFILES[normalize_profile(profile)])
    if overrides:
        unknown = set(overrides) - set(values)
        if unknown:
            raise ValueError(f"unsupported research overrides: {sorted(unknown)}")
        values.update(overrides)
    return values
