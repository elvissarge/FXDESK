import unittest

import numpy as np
import pandas as pd

from fxdesk.backtest.analysis import (
    analyze_result,
    benchmark_metrics,
    buy_and_hold_equity,
    monte_carlo_trades,
)
from fxdesk.backtest.engine import BacktestResult


def price_frame():
    index = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    close = [1.00, 1.10, 1.05, 1.20, 1.15]
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


def trade_frame(profits):
    return pd.DataFrame({"profit": profits, "pips": profits})


class BenchmarkTests(unittest.TestCase):
    def test_buy_and_hold_scales_with_price(self):
        equity = buy_and_hold_equity(price_frame(), 10000.0)
        self.assertAlmostEqual(float(equity.iloc[0]), 10000.0)
        self.assertAlmostEqual(float(equity.iloc[1]), 11000.0)
        self.assertAlmostEqual(float(equity.iloc[-1]), 11500.0)

    def test_buy_and_hold_handles_empty_frame(self):
        self.assertTrue(buy_and_hold_equity(pd.DataFrame(), 10000.0).empty)

    def test_benchmark_metrics_has_standard_keys(self):
        equity = buy_and_hold_equity(price_frame(), 10000.0)
        metrics = benchmark_metrics(equity, "1d", 10000.0)
        self.assertIn("total_return", metrics)
        self.assertAlmostEqual(metrics["total_return"], 0.15, places=4)
        self.assertEqual(metrics["trades"], 0)


class MonteCarloTests(unittest.TestCase):
    def test_deterministic_with_seed(self):
        trades = trade_frame([100.0, -50.0, 200.0, -100.0, 50.0])
        first = monte_carlo_trades(trades, 10000.0, iterations=200, seed=7)
        second = monte_carlo_trades(trades, 10000.0, iterations=200, seed=7)
        self.assertEqual(first, second)

    def test_different_seeds_differ(self):
        trades = trade_frame([100.0, -50.0, 200.0, -100.0, 50.0])
        first = monte_carlo_trades(trades, 10000.0, iterations=200, seed=1)
        second = monte_carlo_trades(trades, 10000.0, iterations=200, seed=2)
        self.assertNotEqual(first, second)

    def test_distribution_summary(self):
        trades = trade_frame([100.0, -50.0, 200.0, -100.0, 50.0])
        stats = monte_carlo_trades(trades, 10000.0, iterations=500, seed=3)
        self.assertEqual(stats["iterations"], 500)
        self.assertEqual(stats["trades_per_run"], 5)
        self.assertGreaterEqual(stats["prob_profit"], 0.0)
        self.assertLessEqual(stats["prob_profit"], 1.0)
        self.assertLessEqual(stats["p05_final"], stats["median_final"])
        self.assertLessEqual(stats["median_final"], stats["p95_final"])
        self.assertLessEqual(stats["median_max_drawdown"], 0.0)

    def test_empty_trades(self):
        stats = monte_carlo_trades(pd.DataFrame(), 10000.0)
        self.assertEqual(stats["iterations"], 0)
        self.assertEqual(stats["prob_profit"], 0.0)


class AnalyzeResultTests(unittest.TestCase):
    def test_builds_benchmark_and_monte_carlo(self):
        index = price_frame().index
        equity = pd.Series(
            np.linspace(10000.0, 10400.0, len(index)), index=index, name="equity"
        )
        result = BacktestResult(
            symbol="EURUSD",
            timeframe="1d",
            strategy="test",
            initial_balance=10000.0,
            final_balance=10400.0,
            equity=equity,
            trades=trade_frame([200.0, 200.0]),
            metrics={"total_return": 0.04, "trades": 2},
        )

        analysis = analyze_result(
            result, price_frame(), monte_carlo_iterations=100, seed=5
        )

        self.assertIn("buy_hold", analysis)
        self.assertIn("comparison", analysis)
        self.assertIn("monte_carlo", analysis)
        self.assertEqual(analysis["monte_carlo"]["iterations"], 100)
        self.assertAlmostEqual(
            analysis["comparison"]["excess_return"],
            0.04 - analysis["comparison"]["buy_hold_return"],
            places=8,
        )

    def test_monte_carlo_skipped_when_not_requested(self):
        index = price_frame().index
        result = BacktestResult(
            symbol="EURUSD",
            timeframe="1d",
            strategy="test",
            initial_balance=10000.0,
            final_balance=10000.0,
            equity=pd.Series(10000.0, index=index),
            trades=trade_frame([]),
            metrics={"total_return": 0.0},
        )
        analysis = analyze_result(result, price_frame())
        self.assertIn("buy_hold", analysis)
        self.assertNotIn("monte_carlo", analysis)


if __name__ == "__main__":
    unittest.main()
