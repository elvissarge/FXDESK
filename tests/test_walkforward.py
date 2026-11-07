import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fxdesk.backtest.walkforward import (
    DEFAULT_GRIDS,
    WalkForward,
    save_walkforward_outputs,
)
from fxdesk.config import load_config


def synthetic_frame(n=700):
    index = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(11)
    trend = np.linspace(1.08, 1.14, n)
    wave = 0.004 * np.sin(np.arange(n) / 12.0)
    noise = np.cumsum(rng.normal(0.0, 0.0002, n))
    close = trend + wave + noise
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.0006,
            "low": close - 0.0006,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )


GRID = {"fast": [10, 20], "slow": [30], "trend": [100]}


class WalkForwardTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["backtest"].update(
            {
                "spread_pips": 0.5,
                "slippage_pips": 0.1,
                "commission_per_lot": 0.0,
                "warmup_bars": 0,
            }
        )
        self.config["walkforward"].update(
            {
                "train_bars": 250,
                "test_bars": 100,
                "step_bars": 100,
                "min_train_trades": 0,
                "objective": "total_return",
                "max_combinations": 20,
            }
        )
        self.frame = synthetic_frame()
        self.walkforward = WalkForward(
            self.config,
            "trend_ma",
            param_grid=GRID,
            monte_carlo_iterations=25,
            seed=4,
        )

    def test_runs_multiple_windows(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        self.assertGreaterEqual(len(result.windows), 2)
        self.assertFalse(result.equity.empty)
        self.assertAlmostEqual(result.final_balance, float(result.equity.iloc[-1]))

    def test_best_params_come_from_grid(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        for window in result.windows:
            params = window["params"]
            self.assertEqual(set(params), set(GRID))
            for key, values in GRID.items():
                self.assertIn(params[key], values)

    def test_metrics_and_analysis_present(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        for key in ("total_return", "sharpe", "max_drawdown", "trades"):
            self.assertIn(key, result.metrics)
        self.assertIn("buy_hold", result.analysis)
        self.assertIn("monte_carlo", result.analysis)
        self.assertEqual(result.analysis["monte_carlo"]["iterations"], 25)

    def test_windows_are_chronological(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        starts = [window["test_start"] for window in result.windows]
        self.assertEqual(starts, sorted(starts))

    def test_to_dict_round_trips(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        payload = result.to_dict()
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertEqual(len(payload["windows"]), len(result.windows))
        self.assertIn("metrics", payload)

    def test_summary_mentions_windows(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        summary = result.summary()
        self.assertIn("Walk-forward", summary)
        self.assertIn("Windows", summary)

    def test_saves_outputs(self):
        result = self.walkforward.run("EURUSD", "1h", self.frame)
        with tempfile.TemporaryDirectory() as tmp:
            paths = save_walkforward_outputs(result, tmp, plot=False)
            for path in paths.values():
                self.assertTrue(Path(path).exists(), path)
            summary = json.loads(
                Path(paths["summary"]).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["strategy"], "trend_ma")

    def test_uses_config_param_grid_when_none_given(self):
        self.config["walkforward"]["param_grid"] = {"trend_ma": GRID}
        walkforward = WalkForward(self.config, "trend_ma")
        self.assertEqual(walkforward.param_grid, GRID)

    def test_default_grids_cover_all_strategies(self):
        for name in ("trend_ma", "breakout", "mean_reversion", "composite"):
            self.assertIn(name, DEFAULT_GRIDS)


if __name__ == "__main__":
    unittest.main()
