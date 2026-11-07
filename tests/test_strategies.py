import unittest

import numpy as np
import pandas as pd

from fxdesk.config import load_config
from fxdesk.strategies.registry import build_strategy, strategy_names


def trending_frame(n=700):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(3)
    drift = np.linspace(0, 0.03, n)
    noise = np.cumsum(rng.normal(0, 0.0003, n))
    close = 1.10 + drift + noise
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0007,
            "low": close - 0.0007,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.frame = trending_frame()

    def test_registry(self):
        self.assertEqual(
            set(strategy_names()),
            {"trend_ma", "breakout", "mean_reversion", "composite"},
        )

    def test_frames_have_required_columns(self):
        for name in strategy_names():
            strategy = build_strategy(name, self.config)
            frame = strategy.generate_frame(self.frame)
            for column in (
                "signal",
                "score",
                "stop_distance",
                "stop_loss",
                "take_profit",
                "rr",
            ):
                self.assertIn(column, frame.columns, name)
            self.assertTrue(set(frame["signal"].unique()).issubset({-1, 0, 1}))

    def test_latest_signal_levels_are_ordered(self):
        strategy = build_strategy("trend_ma", self.config)
        signal = strategy.latest_signal(
            "EURUSD", "1h", self.frame, allow_continuation=True
        )
        self.assertIsNotNone(signal)
        if signal.direction == "long":
            self.assertLess(signal.stop_loss, signal.entry)
            self.assertGreater(signal.take_profit, signal.entry)
        else:
            self.assertGreater(signal.stop_loss, signal.entry)
            self.assertLess(signal.take_profit, signal.entry)
        self.assertGreater(signal.risk_reward, 0)

    def test_composite_has_vote_columns(self):
        strategy = build_strategy("composite", self.config)
        frame = strategy.generate_frame(self.frame)
        vote_columns = [column for column in frame.columns if column.startswith("vote_")]
        self.assertGreaterEqual(len(vote_columns), 1)


if __name__ == "__main__":
    unittest.main()
