import contextlib
import io
import json
import unittest
from argparse import Namespace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fxdesk.brokers.base import OrderRequest, Quote
from fxdesk.brokers.mt5 import MT5Broker
from fxdesk.cli import cmd_mt5
from fxdesk.config import load_config


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008

    def __init__(self):
        self.selected = []
        self.orders = []
        self.select_ok = True
        self.initialized = False
        self.shutdown_called = False
        self._account = SimpleNamespace(
            balance=10000.0,
            equity=10050.0,
            currency="USD",
            leverage=100,
            margin_free=9000.0,
            company="FakeBroker",
        )
        self._symbol = SimpleNamespace(
            digits=5,
            point=0.00001,
            trade_contract_size=100000.0,
            volume_min=0.01,
            volume_step=0.01,
            volume_max=50.0,
            spread=10,
            filling_mode=2,
        )
        self._tick = SimpleNamespace(bid=1.10000, ask=1.10002, time=1700000000)
        self._positions = []
        self._result = SimpleNamespace(
            retcode=10009, order=123, deal=456, price=1.10002, comment="done"
        )

    def initialize(self, **kwargs):
        self.initialized = True
        return True

    def shutdown(self):
        self.shutdown_called = True
        return True

    def last_error(self):
        return (0, "ok")

    def symbol_select(self, symbol, enable=True):
        self.selected.append(symbol)
        return self.select_ok

    def account_info(self):
        return self._account

    def symbol_info(self, symbol):
        return self._symbol

    def symbol_info_tick(self, symbol):
        return self._tick

    def order_send(self, payload):
        self.orders.append(payload)
        return self._result

    def positions_get(self, ticket=None):
        if ticket is None:
            return tuple(self._positions)
        return tuple(item for item in self._positions if item.ticket == ticket)


class MT5BrokerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.config["mt5"]["symbol_suffix"] = ".a"
        self.fake = FakeMT5()
        self.broker = MT5Broker(self.config, module=self.fake)

    def _position(self):
        return SimpleNamespace(
            ticket=42,
            symbol="EURUSD.a",
            type=0,
            volume=0.5,
            price_open=1.10000,
            sl=1.09000,
            tp=1.12000,
            profit=12.5,
            time=1700000000,
            comment="trend_ma",
        )

    def test_available_with_injected_module(self):
        self.assertTrue(self.broker.available())

    def test_account_info(self):
        info = self.broker.account_info()
        self.assertAlmostEqual(info.balance, 10000.0)
        self.assertAlmostEqual(info.equity, 10050.0)
        self.assertEqual(info.currency, "USD")
        self.assertEqual(info.broker, "FakeBroker")

    def test_symbol_info_maps_metadata(self):
        info = self.broker.symbol_info("EURUSD")
        self.assertEqual(info.symbol, "EURUSD")
        self.assertEqual(info.digits, 5)
        self.assertAlmostEqual(info.pip_size, 0.0001)
        self.assertAlmostEqual(info.contract_size, 100000.0)
        self.assertAlmostEqual(info.min_lot, 0.01)
        self.assertAlmostEqual(info.spread, 10 * 0.00001)

    def test_quote_uses_suffix_and_time(self):
        quote = self.broker.quote("EURUSD")
        self.assertEqual(self.fake.selected[-1], "EURUSD.a")
        self.assertAlmostEqual(quote.bid, 1.10)
        self.assertAlmostEqual(quote.ask, 1.10002)
        self.assertIsNotNone(quote.time)
        self.assertEqual(quote.time.tzinfo, timezone.utc)

    def test_place_order_payload(self):
        result = self.broker.place_order(
            OrderRequest("EURUSD", "buy", 0.1, stop_loss=1.09, take_profit=1.12)
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.ticket, 123)
        self.assertAlmostEqual(result.price, 1.10002)

        payload = self.fake.orders[-1]
        self.assertEqual(payload["symbol"], "EURUSD.a")
        self.assertEqual(payload["type"], FakeMT5.ORDER_TYPE_BUY)
        self.assertAlmostEqual(payload["volume"], 0.1)
        self.assertAlmostEqual(payload["sl"], 1.09)
        self.assertAlmostEqual(payload["tp"], 1.12)
        self.assertEqual(payload["type_filling"], FakeMT5.ORDER_FILLING_IOC)
        self.assertEqual(payload["deviation"], 20)

    def test_place_order_invalid_side(self):
        result = self.broker.place_order(OrderRequest("EURUSD", "hold", 0.1))
        self.assertFalse(result.ok)
        self.assertIn("invalid side", result.message)
        self.assertEqual(self.fake.orders, [])

    def test_place_order_missing_symbol(self):
        self.fake.select_ok = False
        result = self.broker.place_order(OrderRequest("EURUSD", "buy", 0.1))
        self.assertFalse(result.ok)
        self.assertIn("not found", result.message)

    def test_order_rejected_returns_message(self):
        self.fake._result = SimpleNamespace(
            retcode=10013, order=0, deal=0, price=0.0, comment="invalid stops"
        )
        result = self.broker.place_order(OrderRequest("EURUSD", "buy", 0.1))
        self.assertFalse(result.ok)
        self.assertIn("invalid stops", result.message)
        self.assertEqual(result.retcode, 10013)

    def test_explicit_filling_mode(self):
        self.config["mt5"]["filling"] = "fok"
        broker = MT5Broker(self.config, module=self.fake)
        broker.place_order(OrderRequest("EURUSD", "sell", 0.1))
        self.assertEqual(
            self.fake.orders[-1]["type_filling"], FakeMT5.ORDER_FILLING_FOK
        )

    def test_positions_parse_strips_suffix(self):
        self.fake._positions = [self._position()]
        positions = self.broker.positions()
        self.assertEqual(len(positions), 1)
        position = positions[0]
        self.assertEqual(position.ticket, 42)
        self.assertEqual(position.symbol, "EURUSD")
        self.assertEqual(position.side, "buy")
        self.assertAlmostEqual(position.volume, 0.5)
        self.assertAlmostEqual(position.stop_loss, 1.09)
        self.assertAlmostEqual(position.profit, 12.5)
        self.assertEqual(position.comment, "trend_ma")

    def test_close_position_reverses_side(self):
        self.fake._positions = [self._position()]
        self.fake._result = SimpleNamespace(
            retcode=10009, order=0, deal=789, price=1.10000, comment="done"
        )
        result = self.broker.close_position(42)
        self.assertTrue(result.ok)
        self.assertEqual(result.ticket, 42)

        payload = self.fake.orders[-1]
        self.assertEqual(payload["type"], FakeMT5.ORDER_TYPE_SELL)
        self.assertEqual(payload["position"], 42)
        self.assertAlmostEqual(payload["price"], 1.10000)
        self.assertEqual(payload["comment"], "fxdesk close")

    def test_close_missing_position(self):
        result = self.broker.close_position(999)
        self.assertFalse(result.ok)
        self.assertIn("not found", result.message)


class FakeCLIBroker:
    instances = []

    def __init__(self, config):
        self.config = config
        self.disconnected = False
        FakeCLIBroker.instances.append(self)

    def available(self):
        return True

    def disconnect(self):
        self.disconnected = True

    def quote(self, symbol):
        return Quote(
            symbol=symbol,
            bid=1.1,
            ask=1.1002,
            time=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        )


class MT5CommandTests(unittest.TestCase):
    def test_mt5_quote_json(self):
        FakeCLIBroker.instances = []
        config = load_config()
        output = io.StringIO()
        with patch("fxdesk.cli.MT5Broker", FakeCLIBroker):
            with contextlib.redirect_stdout(output):
                code = cmd_mt5(
                    Namespace(mt5_command="quote", symbol="EURUSD", json=True),
                    config,
                )

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertAlmostEqual(payload["bid"], 1.1)
        self.assertAlmostEqual(payload["ask"], 1.1002)
        self.assertTrue(FakeCLIBroker.instances[-1].disconnected)

    def test_mt5_unavailable(self):
        class Missing:
            def __init__(self, config):
                pass

            def available(self):
                return False

        config = load_config()
        error = io.StringIO()
        with patch("fxdesk.cli.MT5Broker", Missing):
            with contextlib.redirect_stderr(error):
                code = cmd_mt5(
                    Namespace(mt5_command="quote", symbol="EURUSD", json=False),
                    config,
                )

        self.assertEqual(code, 1)
        self.assertIn("not installed", error.getvalue())


if __name__ == "__main__":
    unittest.main()
