import unittest

import numpy as np
import pandas as pd

from fxdesk.backtest.costs import CostModel, parse_session_multipliers
from fxdesk.backtest.engine import Backtester
from fxdesk.config import load_config


def base_config(**overrides):
    config = load_config()
    config["backtest"].update(
        {
            "spread_pips": 1.0,
            "slippage_pips": 0.0,
            "commission_per_lot": 0.0,
            "swap_pips_per_day": 0.0,
            "warmup_bars": 0,
            "close_at_end": False,
        }
    )
    config["backtest"].update(overrides)
    return config


def trade_setup(hit_stop=False):
    n = 40
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    price = np.full(n, 1.10)
    frame = pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 100.0},
        index=index,
    )
    if hit_stop:
        frame.loc[index[11], ["open", "high", "low", "close"]] = [
            1.10,
            1.101,
            1.098,
            1.099,
        ]
    else:
        frame.loc[index[11], ["open", "high", "low", "close"]] = [
            1.10,
            1.103,
            1.0995,
            1.102,
        ]
    signals = pd.DataFrame(
        {"signal": 0, "stop_distance": np.nan, "rr": 2.0, "atr": 0.0005},
        index=index,
        dtype="float64",
    )
    signals.loc[index[10], "signal"] = 1
    signals.loc[index[10], "stop_distance"] = 0.001
    return frame, signals


class SessionMultiplierTests(unittest.TestCase):
    def test_plain_ranges(self):
        multipliers = parse_session_multipliers({"0-6": 1.5, "12-16": 0.9})
        self.assertEqual(multipliers[0], 1.5)
        self.assertEqual(multipliers[5], 1.5)
        self.assertEqual(multipliers[6], 1.0)
        self.assertEqual(multipliers[12], 0.9)
        self.assertEqual(multipliers[16], 1.0)

    def test_wraparound_range(self):
        multipliers = parse_session_multipliers({"22-2": 2.0})
        self.assertEqual(multipliers[23], 2.0)
        self.assertEqual(multipliers[0], 2.0)
        self.assertEqual(multipliers[1], 2.0)
        self.assertEqual(multipliers[2], 1.0)
        self.assertEqual(multipliers[12], 1.0)

    def test_invalid_entries_are_ignored(self):
        multipliers = parse_session_multipliers({"nope": 5, "0-6": "bad"})
        self.assertEqual(multipliers, [1.0] * 24)


class CostModelTests(unittest.TestCase):
    def test_disabled_without_block(self):
        cost = CostModel(base_config())
        self.assertFalse(cost.enabled)
        self.assertEqual(cost.spread_pips("2024-01-01T03:00:00Z"), 1.0)

    def test_session_multiplier_scales_spread(self):
        config = base_config(
            cost_model={
                "enabled": True,
                "session_spread_multipliers": {"0-6": 2.0},
            }
        )
        cost = CostModel(config)
        self.assertTrue(cost.enabled)
        self.assertAlmostEqual(cost.spread_pips("2024-01-01T03:00:00Z"), 2.0)
        self.assertAlmostEqual(cost.spread_pips("2024-01-01T12:00:00Z"), 1.0)

    def test_volatility_increases_spread(self):
        config = base_config(
            cost_model={"enabled": True, "volatility_spread_mult": 1.0}
        )
        cost = CostModel(config)
        quiet = cost.spread_pips("2024-01-01T12:00:00Z", atr=0.0, price=1.1, pip=0.0001)
        busy = cost.spread_pips(
            "2024-01-01T12:00:00Z", atr=0.0005, price=1.1, pip=0.0001
        )
        self.assertAlmostEqual(quiet, 1.0)
        self.assertAlmostEqual(busy, 6.0)

    def test_caps_are_enforced(self):
        config = base_config(
            cost_model={
                "enabled": True,
                "volatility_spread_mult": 10.0,
                "max_spread_pips": 4.0,
                "volatility_slippage_mult": 10.0,
                "max_slippage_pips": 2.0,
            }
        )
        cost = CostModel(config)
        self.assertAlmostEqual(
            cost.spread_pips("2024-01-01T12:00:00Z", atr=0.001, price=1.1, pip=0.0001),
            4.0,
        )
        self.assertAlmostEqual(
            cost.slippage_pips(
                "2024-01-01T12:00:00Z", atr=0.001, price=1.1, pip=0.0001
            ),
            2.0,
        )


class BacktestCostTests(unittest.TestCase):
    def test_slippage_model_changes_stop_outcome(self):
        frame, signals = trade_setup(hit_stop=True)

        plain = Backtester(base_config()).run("EURUSD", "1h", frame, signals, "test")
        priced = Backtester(
            base_config(
                cost_model={"enabled": True, "volatility_slippage_mult": 5.0}
            )
        ).run("EURUSD", "1h", frame, signals, "test")

        self.assertEqual(len(plain.trades), 1)
        self.assertEqual(len(priced.trades), 1)
        self.assertEqual(priced.trades.iloc[0]["reason"], "stop_loss")
        self.assertLess(priced.final_balance, plain.final_balance)

    def test_spread_model_shifts_entry(self):
        frame, signals = trade_setup()

        plain = Backtester(base_config()).run("EURUSD", "1h", frame, signals, "test")
        priced = Backtester(
            base_config(
                cost_model={"enabled": True, "volatility_spread_mult": 0.1}
            )
        ).run("EURUSD", "1h", frame, signals, "test")

        self.assertGreater(
            priced.trades.iloc[0]["entry_price"],
            plain.trades.iloc[0]["entry_price"],
        )

    def test_absent_cost_model_matches_fixed_costs(self):
        frame, signals = trade_setup()
        result = Backtester(base_config()).run(
            "EURUSD", "1h", frame, signals, "test"
        )
        self.assertAlmostEqual(result.final_balance, 10200.0, places=2)


if __name__ == "__main__":
    unittest.main()
