"""JSON-safe conversion helpers for the web API."""

from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd


def jsonable(value: Any) -> Any:
    """Recursively convert numpy/pandas/datetime values into JSON types."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date, time)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (pd.Timedelta,)):
        return str(value)
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, pd.Series):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return jsonable(value.to_dict(orient="records"))
    return value


def equity_points(equity: pd.Series | None, limit: int = 1500) -> list[dict[str, Any]]:
    """Downsample an equity curve for charting while keeping the last point."""
    if equity is None or len(equity) == 0:
        return []

    series = pd.to_numeric(equity, errors="coerce").dropna()
    if series.empty:
        return []

    step = max(1, math.ceil(len(series) / max(int(limit), 2)))
    sampled = series.iloc[::step]
    if sampled.index[-1] != series.index[-1]:
        sampled = pd.concat([sampled, series.iloc[[-1]]])

    return [
        {"time": pd.Timestamp(index).isoformat(), "value": float(value)}
        for index, value in sampled.items()
    ]


def trades_records(trades: pd.DataFrame | None, limit: int = 2000) -> list[dict[str, Any]]:
    if trades is None or len(trades) == 0:
        return []
    return jsonable(trades.tail(int(limit)).to_dict(orient="records"))


def frame_records(frame: pd.DataFrame | None, limit: int = 500) -> list[dict[str, Any]]:
    if frame is None or len(frame) == 0:
        return []
    index_name = frame.index.name or "time"
    reset = frame.tail(int(limit)).reset_index()
    reset = reset.rename(columns={reset.columns[0]: index_name})
    return jsonable(reset.to_dict(orient="records"))
