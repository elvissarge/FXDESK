"""Donchian-channel breakout strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fxdesk.indicators import atr, donchian, ema
from fxdesk.strategies.base import Strategy, apply_adx_gate, make_signal_frame


class BreakoutStrategy(Strategy):
    name = "breakout"
    default_params = {
        "lookback": 20,
        "trend": 200,
        "atr_period": 14,
        "atr_mult": 2.0,
        "rr": 2.0,
        "adx_period": 14,
        "adx_min": 0.0,
    }
    signal_threshold = 0.5

    def required_bars(self) -> int:
        return max(
            int(self.params["lookback"]),
            int(self.params["trend"]),
            int(self.params.get("adx_period", 14)),
        ) + int(self.params["atr_period"]) + 10

    def generate_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        close = frame["close"]
        channels = donchian(
            frame["high"], frame["low"], int(self.params["lookback"])
        )
        upper = channels["upper"].shift(1)
        lower = channels["lower"].shift(1)
        trend = ema(close, int(self.params["trend"]))
        atr_values = atr(
            frame["high"], frame["low"], close, int(self.params["atr_period"])
        )

        raw = pd.Series(0.0, index=close.index, dtype="float64")
        raw[close > upper] = 1.0
        raw[close < lower] = -1.0

        trend_sign = np.sign(close - trend)
        score = (raw * trend_sign).fillna(0.0)
        score = apply_adx_gate(
            score,
            frame["high"],
            frame["low"],
            close,
            int(self.params.get("adx_period", 14)),
            float(self.params.get("adx_min", 0.0)),
        )

        return make_signal_frame(
            close,
            score,
            atr_values,
            float(self.params["atr_mult"]),
            float(self.params["rr"]),
            self.signal_threshold,
        )

    def rationale(self, row: pd.Series) -> str:
        score = float(row.get("score", 0.0) or 0.0)
        return f"Donchian breakout bias {score:+.2f}"
