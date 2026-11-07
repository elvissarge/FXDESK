"""Base interfaces and helpers for market-data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from fxdesk.errors import ProviderError
from fxdesk.timeframes import normalize_timeframe

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]


def to_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = pd.Timestamp(value).to_pydatetime()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def empty_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex([], tz="UTC")
    return pd.DataFrame(columns=OHLCV_COLUMNS, index=index, dtype="float64")


class DataProvider(ABC):
    """A source of OHLCV candles."""

    name = "base"
    supports_intraday = False

    def __init__(self, config: dict[str, Any]):
        self.config = config

    def available(self) -> bool:
        return True

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return raw candles. Implementations may raise ProviderError."""

    def normalize(self, frame: pd.DataFrame, symbol: str, timeframe: str) -> pd.DataFrame:
        """Coerce a provider response into a clean UTC OHLCV frame."""
        normalize_timeframe(timeframe)

        if frame is None or len(frame) == 0:
            return empty_frame()

        df = frame.copy()
        df.columns = [str(col).strip().lower() for col in df.columns]
        df = df.rename(
            columns={
                "date": "time",
                "datetime": "time",
                "timestamp": "time",
                "ticktime": "time",
                "vol": "volume",
                "tickvol": "volume",
            }
        )

        if "time" in df.columns:
            df = df.set_index("time")

        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except (TypeError, ValueError) as exc:
            raise ProviderError(f"{self.name}: invalid datetime index: {exc}") from exc

        for column in ("open", "high", "low", "close"):
            if column not in df.columns:
                if column == "close" and "open" in df.columns:
                    df["close"] = df["open"]
                elif column == "open" and "close" in df.columns:
                    df["open"] = df["close"]
                else:
                    raise ProviderError(f"{self.name}: missing column {column!r}")

        if "volume" not in df.columns:
            df["volume"] = 0.0

        for column in OHLCV_COLUMNS:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        df = df[OHLCV_COLUMNS]
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        df["volume"] = df["volume"].fillna(0.0)

        return df

    @staticmethod
    def resample(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        rule = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "2h": "2h",
            "4h": "4h",
            "8h": "8h",
            "1d": "1D",
            "1w": "1W",
        }[normalize_timeframe(timeframe)]

        out = frame.resample(rule, label="left", closed="left").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        return out.dropna(subset=["open", "high", "low", "close"])
