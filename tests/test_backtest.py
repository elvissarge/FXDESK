import unittest

import numpy as np
import pandas as pd

from fxdesk.backtest.engine import Backtester
from fxdesk.config import load_config


def base_frame(n=30, price=1.10):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 100.0,
        },
        index=index,
        dtype="float64",
    )


def strategy_frame(index, signal_at=10, stop_distance=0.001, rr=2.0):
    frame = pd.DataFrame(
        {
            "signal": 0,
            "stop_distance": np.nan,
            "rr": rr,
        },
        index=index,
        dtype="float64",
    )
    frame.loc[index[signal_at], "signal"] = 1
    frame.loc[index[signal_at], "stop_distance"] = stop_distance
    return frame


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["backtest"].update(
            {
                "spread_pips": 0.0,
                "commission_per_lot": 0.0,
                "slippage_pips": 0.0,
                "warmup_bars": 0,
                "close_at_end": False,
                "swap_pips_per_day": 0.0,
            }
        )
        self.engine = Backtester(self.config)

    def test_take_profit_trade(self):
        frame = base_frame()
        index = frame.index
        frame.loc[index[11], ["open", "high", "low", "close"]] = [
            1.10,
            1.103,
            1.0995,
            1.102,
        ]

        result = self.engine.run(
            "EURUSD", "1h", frame, strategy_frame(index), "test"
        )

        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade["side"], "long")
        self.assertEqual(trade["reason"], "take_profit")
        self.assertAlmostEqual(trade["profit"], 200.0, places=2)
        self.assertAlmostEqual(result.final_balance, 10200.0, places=2)
        self.assertGreater(result.metrics["sharpe"], 0)

    def test_stop_loss_trade(self):
        frame = base_frame()
        index = frame.index
        frame.loc[index[11], ["open", "high", "low", "close"]] = [
            1.10,
            1.101,
            1.098,
            1.099,
        ]

        result = self.engine.run(
            "EURUSD", "1h", frame, strategy_frame(index), "test"
        )

        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade["reason"], "stop_loss")
        self.assertAlmostEqual(trade["profit"], -100.0, places=2)
        self.assertAlmostEqual(result.final_balance, 9900.0, places=2)

    def test_no_signal_keeps_balance(self):
        frame = base_frame()
        empty = pd.DataFrame(
            {"signal": 0, "stop_distance": np.nan, "rr": 2.0}, index=frame.index
        )
        result = self.engine.run("EURUSD", "1h", frame, empty, "test")
        self.assertEqual(len(result.trades), 0)
        self.assertAlmostEqual(result.final_balance, 10000.0)

    def test_short_trade(self):
        frame = base_frame()
        index = frame.index
        frame.loc[index[11], ["open", "high", "low", "close"]] = [
            1.10,
            1.1005,
            1.097,
            1.098,
        ]
        signals = strategy_frame(index)
        signals.loc[index[10], "signal"] = -1

        result = self.engine.run("EURUSD", "1h", frame, signals, "test")

        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade["side"], "short")
        self.assertEqual(trade["reason"], "take_profit")
        self.assertGreater(trade["profit"], 0)


if __name__ == "__main__":
    unittest.main()
