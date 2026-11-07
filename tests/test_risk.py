import unittest

from fxdesk.config import load_config
from fxdesk.risk import RiskManager


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.risk = RiskManager(self.config)

    def test_eurusd_position_size(self):
        decision = self.risk.position_size(
            "EURUSD",
            equity=10000,
            entry=1.1000,
            stop_loss=1.0950,
            risk_reward=2.0,
        )
        self.assertTrue(decision.valid)
        self.assertAlmostEqual(decision.volume, 0.2, places=6)
        self.assertAlmostEqual(decision.risk_amount, 100.0, places=2)
        self.assertAlmostEqual(decision.reward_amount, 200.0, places=2)

    def test_usdjpy_position_size(self):
        decision = self.risk.position_size(
            "USDJPY",
            equity=10000,
            entry=150.0,
            stop_loss=149.5,
            risk_reward=2.0,
        )
        self.assertTrue(decision.valid)
        self.assertAlmostEqual(decision.volume, 0.3, places=6)

    def test_cross_pair_uses_conversion_rate(self):
        decision = self.risk.position_size(
            "EURGBP",
            equity=10000,
            entry=0.8500,
            stop_loss=0.8450,
            risk_reward=2.0,
        )
        self.assertTrue(decision.valid)
        self.assertAlmostEqual(decision.volume, 0.15, places=6)
        self.assertAlmostEqual(decision.risk_amount, 95.25, places=2)

    def test_size_below_min_lot_is_invalid(self):
        decision = self.risk.position_size(
            "EURUSD",
            equity=50,
            entry=1.1000,
            stop_loss=1.0900,
            risk_reward=2.0,
        )
        self.assertFalse(decision.valid)
        self.assertEqual(decision.volume, 0.0)

    def test_validate_levels(self):
        ok, _ = self.risk.validate_levels(
            "long", 1.10, 1.09, 1.12, 2.0, spread_pips=1.0, volume=0.1
        )
        self.assertTrue(ok)

        ok, reason = self.risk.validate_levels(
            "long", 1.10, 1.11, 1.12, 2.0, spread_pips=1.0, volume=0.1
        )
        self.assertFalse(ok)
        self.assertIn("stop", reason)

        ok, reason = self.risk.validate_levels(
            "long", 1.10, 1.09, 1.12, 1.0, spread_pips=1.0, volume=0.1
        )
        self.assertFalse(ok)
        self.assertIn("reward/risk", reason)

        ok, reason = self.risk.validate_levels(
            "long", 1.10, 1.09, 1.12, 2.0, spread_pips=5.0, volume=0.1
        )
        self.assertFalse(ok)
        self.assertIn("spread", reason)


if __name__ == "__main__":
    unittest.main()
