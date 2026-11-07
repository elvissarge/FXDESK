"""Strategy interfaces and signal construction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd

from fxdesk.indicators import adx


@dataclass
class Signal:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float
    strategy: str
    timestamp: pd.Timestamp
    stop_distance: float
    risk_reward: float
    atr: float = 0.0
    rationale: str = ""

    def with_entry(self, entry: float) -> "Signal":
        if self.direction == "long":
            stop = entry - self.stop_distance
            target = entry + self.stop_distance * self.risk_reward
        else:
            stop = entry + self.stop_distance
            target = entry - self.stop_distance * self.risk_reward
        return replace(self, entry=float(entry), stop_loss=float(stop), take_profit=float(target))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = pd.Timestamp(self.timestamp).isoformat()
        return data


def make_signal_frame(
    close: pd.Series,
    score: pd.Series,
    atr_values: pd.Series,
    atr_mult: float,
    rr: float,
    threshold: float,
) -> pd.DataFrame:
    """Turn a continuous [-1, 1] bias into entry events and protective levels."""
    index = close.index
    score = (
        pd.Series(score, index=index, dtype="float64")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .clip(-1.0, 1.0)
    )
    atr_values = pd.Series(atr_values, index=index, dtype="float64")
    stop_distance = (atr_values * atr_mult).where(atr_values > 0)

    previous = score.shift(1)
    long_event = (score >= threshold) & ((previous < threshold) | previous.isna())
    short_event = (score <= -threshold) & ((previous > -threshold) | previous.isna())

    signal = pd.Series(0, index=index, dtype="int64")
    signal[long_event] = 1
    signal[short_event] = -1
    signal = signal.where(stop_distance.notna() & (stop_distance > 0), 0)

    direction = np.sign(score)
    stop_loss = pd.Series(np.nan, index=index, dtype="float64")
    take_profit = pd.Series(np.nan, index=index, dtype="float64")

    long_mask = direction > 0
    short_mask = direction < 0

    stop_loss[long_mask] = close[long_mask] - stop_distance[long_mask]
    stop_loss[short_mask] = close[short_mask] + stop_distance[short_mask]
    take_profit[long_mask] = close[long_mask] + stop_distance[long_mask] * rr
    take_profit[short_mask] = close[short_mask] - stop_distance[short_mask] * rr

    return pd.DataFrame(
        {
            "signal": signal.astype(int),
            "score": score,
            "stop_distance": stop_distance,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "atr": atr_values,
            "confidence": score.abs(),
            "rr": rr,
        }
    )


def apply_adx_gate(
    score: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
    min_adx: float = 0.0,
    max_adx: float = 100.0,
) -> pd.Series:
    """Zero out the bias when ADX is outside the allowed regime band.

    ``min_adx`` favours trend strategies; ``max_adx`` favours mean reversion.
    Defaults (0/100) disable the filter, preserving earlier behaviour.
    """
    min_adx = float(min_adx or 0.0)
    max_adx = float(max_adx if max_adx is not None else 100.0)
    if min_adx <= 0.0 and max_adx >= 100.0:
        return score

    values = adx(high, low, close, int(period))["adx"]
    mask = pd.Series(True, index=score.index)
    if min_adx > 0.0:
        mask &= values >= min_adx
    if max_adx < 100.0:
        mask &= values <= max_adx
    return score.where(mask, 0.0)


class Strategy(ABC):
    name = "base"
    default_params: dict[str, Any] = {}
    signal_threshold = 0.5

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.config = config or {}
        self.params = {**self.default_params, **(params or {})}

    @abstractmethod
    def generate_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a frame with signal/score/stop/target columns on the input index."""

    def required_bars(self) -> int:
        return 250

    def rationale(self, row: pd.Series) -> str:
        score = float(row.get("score", 0.0) or 0.0)
        return f"{self.name} bias {score:+.2f}"

    def latest_signal(
        self,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
        allow_continuation: bool = False,
    ) -> Signal | None:
        if frame is None or frame.empty:
            return None

        prepared = self.generate_frame(frame)
        if prepared.empty:
            return None

        row = prepared.iloc[-1]
        event = int(row.get("signal", 0) or 0)
        score = float(row.get("score", 0.0) or 0.0)

        if event != 0:
            direction = "long" if event > 0 else "short"
            confidence = max(abs(score), 0.01)
        elif allow_continuation and abs(score) >= self.signal_threshold:
            direction = "long" if score > 0 else "short"
            confidence = abs(score)
        else:
            return None

        stop_distance = float(row.get("stop_distance", 0.0) or 0.0)
        if not np.isfinite(stop_distance) or stop_distance <= 0:
            return None

        entry = float(frame["close"].iloc[-1])
        rr = float(self.params.get("rr", row.get("rr", 2.0)))
        atr_value = float(row.get("atr", 0.0) or 0.0)

        if direction == "long":
            stop_loss = entry - stop_distance
            take_profit = entry + stop_distance * rr
        else:
            stop_loss = entry + stop_distance
            take_profit = entry - stop_distance * rr

        return Signal(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confidence=min(max(confidence, 0.0), 1.0),
            strategy=self.name,
            timestamp=pd.Timestamp(prepared.index[-1]),
            stop_distance=stop_distance,
            risk_reward=rr,
            atr=atr_value,
            rationale=self.rationale(row),
        )
