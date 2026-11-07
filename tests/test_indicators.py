import unittest

import numpy as np
import pandas as pd

from fxdesk.indicators import (
    adx,
    atr,
    bollinger,
    donchian,
    ema,
    macd,
    rsi,
    sma,
)


def sample_frame(n=120):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(42)
    close = 1.10 + np.cumsum(rng.normal(0, 0.0005, n))
    high = close + rng.uniform(0.0001, 0.001, n)
    low = close - rng.uniform(0.0001, 0.001, n)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": 1.0},
        index=index,
    )


class IndicatorTests(unittest.TestCase):
    def setUp(self):
        self.frame = sample_frame()

    def test_sma_ema_lengths(self):
        self.assertEqual(len(sma(self.frame["close"], 20)), len(self.frame))
        self.assertEqual(len(ema(self.frame["close"], 20)), len(self.frame))
        self.assertTrue(sma(self.frame["close"], 20).iloc[:19].isna().all())

    def test_rsi_bounds(self):
        values = rsi(self.frame["close"], 14).dropna()
        self.assertGreater(len(values), 0)
        self.assertTrue(((values >= 0) & (values <= 100)).all())

    def test_atr_positive(self):
        values = atr(self.frame["high"], self.frame["low"], self.frame["close"], 14)
        self.assertTrue((values.dropna() > 0).all())

    def test_bollinger_order(self):
        bands = bollinger(self.frame["close"], 20, 2.0).dropna()
        self.assertTrue((bands["upper"] >= bands["mid"]).all())
        self.assertTrue((bands["mid"] >= bands["lower"]).all())

    def test_donchian_and_macd_and_adx(self):
        channels = donchian(self.frame["high"], self.frame["low"], 20).dropna()
        self.assertTrue((channels["upper"] >= channels["lower"]).all())

        macd_frame = macd(self.frame["close"]).dropna()
        self.assertIn("histogram", macd_frame.columns)

        adx_frame = adx(self.frame["high"], self.frame["low"], self.frame["close"])
        self.assertIn("adx", adx_frame.columns)


if __name__ == "__main__":
    unittest.main()
