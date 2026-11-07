"""Simple on-disk OHLCV cache (CSV, no extra dependencies)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from fxdesk.config import ensure_dir
from fxdesk.data.base import OHLCV_COLUMNS, empty_frame
from fxdesk.symbols import clean_symbol
from fxdesk.timeframes import normalize_timeframe


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


class OHLCVCache:
    def __init__(self, directory: str | Path):
        self.directory = ensure_dir(directory)

    def path(self, provider: str, symbol: str, timeframe: str) -> Path:
        tf = normalize_timeframe(timeframe)
        name = f"{_safe(provider)}__{_safe(clean_symbol(symbol))}__{tf}.csv"
        return self.directory / name

    def load(self, provider: str, symbol: str, timeframe: str) -> pd.DataFrame | None:
        path = self.path(provider, symbol, timeframe)
        if not path.exists() or path.stat().st_size == 0:
            return None
        try:
            df = pd.read_csv(path, index_col=0)
        except (pd.errors.EmptyDataError, pd.errors.ParserError):
            return None

        if df.empty:
            return None

        df.index = pd.to_datetime(df.index, utc=True, errors="coerce")
        df = df[df.index.notna()]
        for column in OHLCV_COLUMNS:
            if column not in df.columns:
                df[column] = 0.0
        df = df[OHLCV_COLUMNS].apply(pd.to_numeric, errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"]).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df if len(df) else None

    def save(self, provider: str, symbol: str, timeframe: str, frame: pd.DataFrame) -> None:
        if frame is None or frame.empty:
            return
        path = self.path(provider, symbol, timeframe)
        tmp = path.with_suffix(".tmp")
        frame.to_csv(tmp, index_label="time")
        tmp.replace(path)

    def clear(self) -> None:
        for path in self.directory.glob("*.csv"):
            path.unlink()


def merge_frames(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        return new
    if new is None or new.empty:
        return old
    merged = pd.concat([old, new])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def slice_frame(frame: pd.DataFrame | None, start, end) -> pd.DataFrame:
    if frame is None or frame.empty:
        return empty_frame()
    return frame.loc[start:end]
