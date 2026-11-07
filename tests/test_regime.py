import unittest

import numpy as np
import pandas as pd

from fxdesk.config import load_config
from fxdesk.indicators import adx
from fxdesk.strategies.base import apply_adx_gate
from fxdesk.strategies.registry import build_strategy


def trend_frame(n=600):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = 1.10 + np.linspace(0.0, 0.06, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0002,
            "low": close - 0.0002,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


def range_frame(n=600):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(5)
    close = 1.10 + rng.normal(0.0, 0.0005, n)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0003,
            "low": close - 0.0003,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


def adx_values(frame):
    return adx(frame["high"], frame["low"], frame["close"], 14)["adx"]


class RegimeTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_trending_market_has_high_adx(self):
        self.assertGreater(float(adx_values(trend_frame()).iloc[-1]), 40.0)

    def test_ranging_market_has_low_adx(self):
        self.assertLess(float(adx_values(range_frame()).iloc[-1]), 25.0)

    def test_gate_blocks_ranging_market(self):
        frame = range_frame()
        score = pd.Series(1.0, index=frame.index)
        gated = apply_adx_gate(
            score, frame["high"], frame["low"], frame["close"], min_adx=25.0
        )
        self.assertEqual(float(gated.sum()), 0.0)

    def test_gate_allows_trending_market(self):
        frame = trend_frame()
        score = pd.Series(1.0, index=frame.index)
        gated = apply_adx_gate(
            score, frame["high"], frame["low"], frame["close"], min_adx=25.0
        )
        self.assertGreater(float(gated.sum()), 0.0)

    def test_gate_disabled_returns_score_unchanged(self):
        frame = range_frame()
        score = pd.Series(1.0, index=frame.index)
        gated = apply_adx_gate(score, frame["high"], frame["low"], frame["close"])
        pd.testing.assert_series_equal(gated, score)

    def test_trend_strategy_has_no_signals_in_range_when_gated(self):
        strategy = build_strategy(
            "trend_ma", {**self.config, "strategies": {"trend_ma": {"adx_min": 25.0}}}
        )
        frame = strategy.generate_frame(range_frame())
        self.assertEqual(int(frame["signal"].abs().sum()), 0)

    def test_mean_reversion_has_no_signals_in_trend_when_gated(self):
        strategy = build_strategy(
            "mean_reversion",
            {**self.config, "strategies": {"mean_reversion": {"adx_max": 25.0}}},
        )
        frame = strategy.generate_frame(trend_frame())
        self.assertEqual(int(frame["signal"].abs().sum()), 0)


if __name__ == "__main__":
    unittest.main()
