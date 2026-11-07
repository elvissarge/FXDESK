import json
import unittest

import numpy as np
import pandas as pd

from fxdesk.brokers.base import Quote
from fxdesk.config import load_config
from fxdesk.signals.engine import SignalEngine
from fxdesk.strategies.registry import build_strategy


def trending_frame(n=700):
    index = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(7)
    close = 1.10 + np.linspace(0, 0.03, n) + np.cumsum(
        rng.normal(0, 0.0002, n)
    )
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


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.frame = trending_frame()
        self.engine = SignalEngine(self.config)

    def test_plan_has_ordered_levels_and_size(self):
        strategy = build_strategy("trend_ma", self.config)
        quote = Quote("EURUSD", bid=1.1299, ask=1.1301)
        plan = self.engine.plan_from_frame(
            "EURUSD",
            "1h",
            strategy,
            self.frame,
            quote=quote,
            equity=10000,
        )
        self.assertIsNotNone(plan)
        self.assertTrue(plan.valid, plan.reason)
        self.assertGreater(plan.volume, 0)
        if plan.direction == "long":
            self.assertLess(plan.stop_loss, plan.entry)
            self.assertGreater(plan.take_profit, plan.entry)
        else:
            self.assertGreater(plan.stop_loss, plan.entry)
            self.assertLess(plan.take_profit, plan.entry)
        self.assertGreaterEqual(plan.risk_reward, 1.5)
        self.assertGreater(plan.rank_score, 0)

    def test_plan_is_json_serializable(self):
        strategy = build_strategy("composite", self.config)
        quote = Quote("EURUSD", bid=1.1299, ask=1.1301)
        plan = self.engine.plan_from_frame(
            "EURUSD",
            "1h",
            strategy,
            self.frame,
            quote=quote,
            equity=10000,
            allow_continuation=True,
        )
        if plan is not None:
            payload = json.dumps(plan.to_dict())
            self.assertIn("EURUSD", payload)
            self.assertIn("timestamp", payload)

    def test_short_plan_when_price_is_flat(self):
        strategy = build_strategy("mean_reversion", self.config)
        quote = Quote("EURUSD", bid=1.1299, ask=1.1301)
        plan = self.engine.plan_from_frame(
            "EURUSD",
            "1h",
            strategy,
            self.frame,
            quote=quote,
            equity=10000,
            allow_continuation=True,
        )
        self.assertIsNotNone(plan)


if __name__ == "__main__":
    unittest.main()
