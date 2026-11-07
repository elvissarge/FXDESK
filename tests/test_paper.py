import tempfile
import unittest
from pathlib import Path

from fxdesk.brokers.base import OrderRequest, Quote
from fxdesk.brokers.paper import PaperBroker
from fxdesk.config import load_config


class PaperBrokerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["paper"].update(
            {"slippage_pips": 0.2, "commission_per_lot": 0.0}
        )
        self.broker = PaperBroker(self.config, initial_balance=10000)
        self.broker.update_price("EURUSD", 1.0999, 1.1001)

    def test_open_and_close_profit(self):
        result = self.broker.place_order(
            OrderRequest(
                "EURUSD",
                "buy",
                1.0,
                stop_loss=1.0950,
                take_profit=1.1050,
                comment="test",
            )
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(self.broker.positions()), 1)

        self.broker.update_price("EURUSD", 1.1049, 1.1051)
        self.assertGreater(self.broker.account_info().equity, 10000)

        closed = self.broker.close_position(result.ticket)
        self.assertTrue(closed.ok)
        self.assertGreater(self.broker.balance, 10000)
        self.assertEqual(len(self.broker.positions()), 0)

    def test_stop_loss_auto_close(self):
        result = self.broker.place_order(
            OrderRequest(
                "EURUSD",
                "buy",
                0.1,
                stop_loss=1.0950,
                take_profit=1.1100,
            )
        )
        self.assertTrue(result.ok)

        closed = self.broker.process_quote(
            Quote("EURUSD", bid=1.0940, ask=1.0942)
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].reason, "stop_loss")
        self.assertLess(self.broker.balance, 10000)
        self.assertEqual(len(self.broker.positions()), 0)

    def test_take_profit_auto_close(self):
        result = self.broker.place_order(
            OrderRequest(
                "EURUSD",
                "buy",
                0.1,
                stop_loss=1.0950,
                take_profit=1.1050,
            )
        )
        self.assertTrue(result.ok)

        closed = self.broker.process_quote(
            Quote("EURUSD", bid=1.1051, ask=1.1053)
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0].reason, "take_profit")
        self.assertGreater(self.broker.balance, 10000)

    def test_state_round_trip(self):
        self.broker.place_order(
            OrderRequest("EURUSD", "buy", 0.5, stop_loss=1.0950, take_profit=1.1050)
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper_state.json"
            self.broker.save_state(path)
            self.assertTrue(path.exists())

            restored = PaperBroker(self.config, initial_balance=1.0)
            self.assertTrue(restored.load_state(path))
            self.assertAlmostEqual(restored.balance, self.broker.balance)
            self.assertEqual(len(restored.positions()), 1)
            self.assertEqual(restored.positions()[0].symbol, "EURUSD")

    def test_rejects_invalid_order(self):
        bad_side = self.broker.place_order(OrderRequest("EURUSD", "hold", 1.0))
        self.assertFalse(bad_side.ok)

        bad_volume = self.broker.place_order(OrderRequest("EURUSD", "buy", 0.0))
        self.assertFalse(bad_volume.ok)


if __name__ == "__main__":
    unittest.main()
