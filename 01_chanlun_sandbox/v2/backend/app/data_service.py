from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .models import MarketBar
from .storage import Storage


INDEX_NAMES = {
    "sh000001": "上证指数",
    "sh000016": "上证50",
    "sh000300": "沪深300",
    "sh000852": "中证1000",
    "sh000905": "中证500",
}

KNOWN_NAMES = {
    "sz002384": "东山精密",
    "sz002463": "沪电股份",
    "sh603078": "江化微",
    "sz002709": "天赐材料",
    "sh588200": "科创芯片ETF",
}

REQUIRED_COLUMNS = ["time", "open", "high", "low", "close", "volume", "amount"]


class DataQualityError(ValueError):
    pass


class DataService:
    def __init__(self, data_dir: Path, storage: Storage):
        self.data_dir = data_dir
        self.storage = storage
        self._cache: dict[tuple[str, str], tuple[int, pd.DataFrame, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def normalize_symbol(value: str) -> str:
        text = str(value).strip().lower()
        match = re.fullmatch(r"([a-z]{0,2})(\d{6})", text)
        if not match:
            raise ValueError("请输入6位代码，可带sh/sz前缀")
        prefix, code = match.groups()
        if not prefix:
            prefix = "sh" if code.startswith("6") or code in {"000001", "000016", "000300", "000852", "000905"} else "sz"
        if prefix not in {"sh", "sz"}:
            raise ValueError("股票代码前缀只能是sh或sz")
        return f"{prefix}{code}"

    def period_file(self, symbol: str, level: str) -> Path:
        symbol = self.normalize_symbol(symbol)
        period = {"5m": "5Min", "30m": "30Min"}.get(level)
        if not period:
            raise ValueError(f"unsupported level: {level}")
        return self.data_dir / f"{symbol}_{period}_MaxAvailable.csv"

    def list_stocks(self) -> list[dict[str, Any]]:
        found: dict[str, set[str]] = {}
        if self.data_dir.exists():
            for path in self.data_dir.glob("*_MaxAvailable.csv"):
                match = re.fullmatch(r"(.+?)_(5Min|30Min)_MaxAvailable\.csv", path.name)
                if not match:
                    continue
                symbol, period = match.groups()
                found.setdefault(symbol, set()).add("5m" if period == "5Min" else "30m")
        metadata = self.storage.instrument_metadata()
        stocks: list[dict[str, Any]] = []
        for symbol, periods in sorted(found.items()):
            meta = metadata.get(symbol, {})
            name = meta.get("name") or INDEX_NAMES.get(symbol) or KNOWN_NAMES.get(symbol) or ""
            latest = max(
                (self.period_file(symbol, level).stat().st_mtime for level in periods),
                default=0,
            )
            self.storage.upsert_instrument(symbol, name, sorted(periods))
            stocks.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "periods": sorted(periods),
                    "last_synced_at": meta.get("last_synced_at"),
                    "updated_at_epoch": latest,
                    "quality": "ready" if {"5m", "30m"}.issubset(periods) else "partial",
                }
            )
        return stocks

    def load_frame(self, symbol: str, level: str, as_of: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
        symbol = self.normalize_symbol(symbol)
        path = self.period_file(symbol, level)
        if not path.exists():
            raise FileNotFoundError(f"缺少行情文件: {path.name}")
        stamp = path.stat().st_mtime_ns
        key = (symbol, level)
        with self._lock:
            cached = self._cache.get(key)
            if not cached or cached[0] != stamp:
                frame = pd.read_csv(path)
                frame, quality = self.validate_frame(frame, path)
                self._cache[key] = (stamp, frame, quality)
            else:
                frame, quality = cached[1], cached[2]
        sliced = frame
        if as_of is not None:
            sliced = sliced.loc[sliced["time"] <= pd.Timestamp(as_of)]
        if sliced.empty:
            raise DataQualityError(f"{symbol} {level} 在指定时间前没有行情")
        return sliced.reset_index(drop=True).copy(), dict(quality)

    @staticmethod
    def validate_frame(frame: pd.DataFrame, path: Path | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise DataQualityError(f"{path or 'CSV'} 缺少字段: {missing}")
        data = frame[REQUIRED_COLUMNS].copy()
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        for column in REQUIRED_COLUMNS[1:]:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        if data.isna().any().any():
            raise DataQualityError(f"{path or 'CSV'} 存在无法解析的时间或数值")
        data = data.sort_values("time").reset_index(drop=True)
        if data["time"].duplicated().any():
            raise DataQualityError(f"{path or 'CSV'} 存在重复时间")
        upper = data[["open", "close", "low"]].max(axis=1)
        lower = data[["open", "close", "high"]].min(axis=1)
        if (data["high"] < upper).any() or (data["low"] > lower).any():
            raise DataQualityError(f"{path or 'CSV'} OHLC边界不合法")
        if (data["volume"] < 0).any() or (data["amount"] < 0).any():
            raise DataQualityError(f"{path or 'CSV'} 成交量或成交额为负")
        denominator = data["volume"].replace(0, np.nan)
        data["effective_amount"] = data["amount"].where(data["amount"] > 0, data["close"] * data["volume"])
        data["vwap"] = (data["effective_amount"] / denominator).replace([np.inf, -np.inf], np.nan)
        scale = np.nanmedian(data["close"] / data["vwap"])
        if np.isfinite(scale) and (scale > 10 or scale < 0.1):
            data["vwap"] *= scale
        data["vwap"] = data["vwap"].fillna(data["close"])
        quality = {
            "status": "ready",
            "rows": len(data),
            "start": data.iloc[0]["time"].isoformat(),
            "end": data.iloc[-1]["time"].isoformat(),
            "volume_available": bool((data["volume"] > 0).any()),
            "amount_available": bool((data["amount"] > 0).any()),
            "amount_coverage": round(float((data["amount"] > 0).mean()), 6),
            "duplicates": 0,
            "missing_values": 0,
        }
        return data, quality

    @staticmethod
    def data_hash(frames: list[pd.DataFrame]) -> str:
        digest = hashlib.sha256()
        for frame in frames:
            payload = pd.util.hash_pandas_object(frame[REQUIRED_COLUMNS], index=False).values.tobytes()
            digest.update(payload)
        return digest.hexdigest()

    @staticmethod
    def market_bars(frame: pd.DataFrame) -> list[MarketBar]:
        return [
            MarketBar(
                time=row.time.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
                amount=float(row.amount),
                vwap=float(row.vwap),
            )
            for row in frame.itertuples(index=False)
        ]

    def next_times(self, symbol: str, level: str, after: pd.Timestamp) -> list[pd.Timestamp]:
        frame, _ = self.load_frame(symbol, level)
        return frame.loc[frame["time"] > pd.Timestamp(after), "time"].tolist()

    def sync_symbol(self, symbol: str) -> dict[str, Any]:
        symbol = self.normalize_symbol(symbol)
        results = []
        for level, scale in (("5m", 5), ("30m", 30)):
            path = self.period_file(symbol, level)
            if path.exists():
                existing = pd.read_csv(path)
                existing["time"] = pd.to_datetime(existing["time"])
                last_local_time = existing["time"].max()
                requested_rows = self._incremental_datalen(last_local_time, scale)
            else:
                existing = None
                last_local_time = None
                requested_rows = 1970

            incoming = self._fetch_sina_bars(symbol, scale, requested_rows)
            incoming["time"] = pd.to_datetime(incoming["time"])
            if existing is not None and last_local_time is not None:
                additions = incoming.loc[incoming["time"] > last_local_time].copy()
                merged = pd.concat([existing, additions], ignore_index=True)
                ignored_overlap = len(incoming) - len(additions)
            else:
                merged = incoming
                additions = incoming
                ignored_overlap = 0
            merged["time"] = pd.to_datetime(merged["time"])
            merged = merged.sort_values("time").drop_duplicates("time", keep="first")
            validated, quality = self.validate_frame(merged, path)
            output = validated[REQUIRED_COLUMNS].copy()
            output["time"] = output["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
            if not path.exists() or not additions.empty:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(".tmp")
                output.to_csv(temp, index=False)
                temp.replace(path)
                with self._lock:
                    self._cache.pop((symbol, level), None)
            results.append({
                "level": level,
                "rows": len(output),
                "requested_rows": requested_rows,
                "added_rows": len(additions),
                "ignored_overlap_rows": ignored_overlap,
                "last_time": quality["end"],
            })
        name = self.fetch_name(symbol)
        periods = ["5m", "30m"]
        frames = [self.load_frame(symbol, level)[0] for level in periods]
        digest = self.data_hash(frames)
        self.storage.upsert_instrument(symbol, name, periods, digest, synced=True)
        return {"symbol": symbol, "name": name, "periods": results, "data_hash": digest}

    @staticmethod
    def _incremental_datalen(
        last_local_time: pd.Timestamp,
        scale: int,
        now: pd.Timestamp | None = None,
    ) -> int:
        current = pd.Timestamp.now() if now is None else pd.Timestamp(now)
        start_day = pd.Timestamp(last_local_time).normalize()
        end_day = max(start_day, current.normalize())
        session_count = max(1, len(pd.bdate_range(start_day, end_day)))
        bars_per_session = max(1, 240 // scale)
        # Include the last local session plus two bars of overlap. The merge
        # watermark still prevents these overlap rows from replacing local data.
        return min(1970, max(8, session_count * bars_per_session + 2))

    @staticmethod
    def _fetch_sina_bars(symbol: str, scale: int, datalen: int = 1970) -> pd.DataFrame:
        datalen = max(1, min(int(datalen), 1970))
        url = (
            "https://quotes.sina.cn/cn/api/json_v2.php/"
            f"CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}"
        )
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("在线行情接口没有返回有效数据")
        frame = pd.DataFrame(payload).rename(columns={"day": "time"})
        for column in REQUIRED_COLUMNS:
            if column not in frame.columns:
                if column == "amount":
                    frame[column] = pd.to_numeric(frame["volume"], errors="coerce") * pd.to_numeric(frame["close"], errors="coerce")
                else:
                    raise RuntimeError(f"在线行情缺少字段: {column}")
        return frame[REQUIRED_COLUMNS]

    @staticmethod
    def fetch_name(symbol: str) -> str:
        if symbol in INDEX_NAMES:
            return INDEX_NAMES[symbol]
        if symbol in KNOWN_NAMES:
            fallback = KNOWN_NAMES[symbol]
        else:
            fallback = symbol
        try:
            request = urllib.request.Request(
                f"https://hq.sinajs.cn/list={symbol}",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                raw = response.read().decode("gb18030", errors="replace")
            match = re.search(r'=\"([^,\"]+)', raw)
            return match.group(1).strip() if match and match.group(1).strip() else fallback
        except Exception:
            return fallback
