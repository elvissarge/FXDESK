"""Vote-based composite strategy."""

from __future__ import annotations

import pandas as pd

from fxdesk.indicators import atr
from fxdesk.strategies.base import Strategy, make_signal_frame


class CompositeStrategy(Strategy):
    name = "composite"
    default_params = {
        "min_score": 0.6,
        "strategies": ["trend_ma", "breakout", "mean_reversion"],
        "atr_period": 14,
        "atr_mult": 2.0,
        "rr": 2.0,
    }

    def __init__(self, params=None, config=None):
        super().__init__(params=params, config=config)
        self.signal_threshold = float(self.params["min_score"])

        from fxdesk.strategies.registry import build_strategy

        self.sub_strategies = [
            build_strategy(name, self.config) for name in self.params["strategies"]
        ]

    def required_bars(self) -> int:
        if not self.sub_strategies:
            return 250
        return max(strategy.required_bars() for strategy in self.sub_strategies)

    def generate_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        close = frame["close"]
        scores: list[pd.Series] = []
        votes: dict[str, pd.Series] = {}

        for strategy in self.sub_strategies:
            sub_frame = strategy.generate_frame(frame)
            scores.append(sub_frame["score"])
            votes[strategy.name] = sub_frame["score"]

        if scores:
            combined = pd.concat(scores, axis=1).mean(axis=1).fillna(0.0)
        else:
            combined = pd.Series(0.0, index=close.index)

        atr_values = atr(
            frame["high"], frame["low"], close, int(self.params["atr_period"])
        )
        result = make_signal_frame(
            close,
            combined,
            atr_values,
            float(self.params["atr_mult"]),
            float(self.params["rr"]),
            self.signal_threshold,
        )

        for name, series in votes.items():
            result[f"vote_{name}"] = series

        return result

    def rationale(self, row: pd.Series) -> str:
        parts = []
        for key, value in row.items():
            if key.startswith("vote_") and abs(float(value)) > 0:
                parts.append(f"{key[5:]}={float(value):+.2f}")
        return "votes: " + ", ".join(parts) if parts else "no aligned votes"
