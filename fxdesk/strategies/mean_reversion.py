"""Bollinger + RSI mean-reversion strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from fxdesk.indicators import atr, bollinger, rsi
from fxdesk.strategies.base import Strategy, apply_adx_gate, make_signal_frame


class MeanReversionStrategy(Strategy):
    name = "mean_reversion"
    default_params = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "rsi_low": 30.0,
        "rsi_high": 70.0,
        "atr_period": 14,
        "atr_mult": 1.5,
        "rr": 1.5,
        "adx_period": 14,
        "adx_max": 100.0,
    }
    signal_threshold = 0.5

    def required_bars(self) -> int:
        return max(
            int(self.params["bb_period"]),
            int(self.params["rsi_period"]),
            int(self.params["atr_period"]),
            int(self.params.get("adx_period", 14)),
        ) + 10

    def generate_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        close = frame["close"]
        bands = bollinger(
            close,
            int(self.params["bb_period"]),
            float(self.params["bb_std"]),
        )
        rsi_values = rsi(close, int(self.params["rsi_period"]))
        atr_values = atr(
            frame["high"], frame["low"], close, int(self.params["atr_period"])
        )

        zscore = (close - bands["mid"]) / bands["std"].replace(0.0, np.nan)
        score = pd.Series(0.0, index=close.index, dtype="float64")

        long_condition = (zscore <= -float(self.params["bb_std"])) & (
            rsi_values <= float(self.params["rsi_low"])
        )
        short_condition = (zscore >= float(self.params["bb_std"])) & (
            rsi_values >= float(self.params["rsi_high"])
        )

        score[long_condition] = 1.0
        score[short_condition] = -1.0
        score = apply_adx_gate(
            score,
            frame["high"],
            frame["low"],
            close,
            int(self.params.get("adx_period", 14)),
            0.0,
            float(self.params.get("adx_max", 100.0)),
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
        return f"Bollinger/RSI reversion bias {score:+.2f}"
