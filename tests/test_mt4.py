import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fxdesk.brokers.base import OrderRequest
from fxdesk.brokers.mt4 import MT4FileBridgeBroker, _parse_kv, _parse_time
from fxdesk.config import load_config
from fxdesk.errors import BrokerError
from fxdesk.live.feed import DataFeed, MT4Feed, build_feed


class MT4BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.config = load_config()
        self.config["mt4"].update(
            {
                "bridge_dir": str(self.directory),
                "timeout_seconds": 0.5,
                "poll_interval_seconds": 0.01,
            }
        )
        self.broker = MT4FileBridgeBroker(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_available_and_connect(self):
        self.assertTrue(self.broker.available())

        def responder():
            deadline = time.time() + 2
            while time.time() < deadline:
                commands = list(self.directory.glob("cmd_*.txt"))
                if commands:
                    request_id = commands[0].stem[4:]
                    response = self.directory / f"res_{request_id}.txt"
                    response.write_text("OK=1\nMESSAGE=pong\n", encoding="ascii")
                    return
                time.sleep(0.005)

        thread = threading.Thread(target=responder, daemon=True)
        thread.start()
        self.broker.connect()
        thread.join(timeout=2)

    def test_quote_round_trip(self):
        def responder():
            deadline = time.time() + 2
            while time.time() < deadline:
                commands = list(self.directory.glob("cmd_*.txt"))
                if commands:
                    request_id = commands[0].stem[4:]
                    response = self.directory / f"res_{request_id}.txt"
                    response.write_text(
                        "OK=1\nBID=1.10000\nASK=1.10002\n"
                        "TIME=2024.01.01 12:00:00\n",
                        encoding="ascii",
                    )
                    return
                time.sleep(0.005)

        thread = threading.Thread(target=responder, daemon=True)
        thread.start()
        quote = self.broker.quote("EURUSD")
        thread.join(timeout=2)

        self.assertAlmostEqual(quote.bid, 1.10)
        self.assertAlmostEqual(quote.ask, 1.10002)
        self.assertEqual(quote.time.year, 2024)

    def test_timeout_raises(self):
        broker = MT4FileBridgeBroker(self.config)
        broker.timeout = 0.05
        with self.assertRaises(BrokerError):
            broker.connect()

    def test_missing_directory_raises(self):
        self.config["mt4"]["bridge_dir"] = str(self.directory / "missing")
        broker = MT4FileBridgeBroker(self.config)
        self.assertFalse(broker.available())
        with self.assertRaises(BrokerError):
            broker.connect()

    def test_positions_parse(self):
        raw = (
            "OK=1\n"
            "POSITION=42|EURUSD|buy|0.50|1.10000|1.09000|1.12000|12.50|"
            "trend_ma|2024.01.01 12:00:00\n"
        )
        with patch.object(
            self.broker, "_request", return_value={"OK": "1", "__raw__": raw}
        ):
            positions = self.broker.positions()

        self.assertEqual(len(positions), 1)
        position = positions[0]
        self.assertEqual(position.ticket, 42)
        self.assertEqual(position.symbol, "EURUSD")
        self.assertEqual(position.side, "buy")
        self.assertAlmostEqual(position.volume, 0.5)
        self.assertAlmostEqual(position.stop_loss, 1.09)
        self.assertAlmostEqual(position.profit, 12.5)

    def test_place_order_parse(self):
        with patch.object(
            self.broker,
            "_request",
            return_value={"OK": "1", "TICKET": "7", "PRICE": "1.10001", "RETCODE": "0"},
        ):
            result = self.broker.place_order(
                OrderRequest("EURUSD", "buy", 0.1, stop_loss=1.09, take_profit=1.12)
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.ticket, 7)
        self.assertAlmostEqual(result.price, 1.10001)

    def test_build_feed_falls_back_without_bridge(self):
        self.config["mt4"]["bridge_dir"] = str(self.directory / "missing")
        with patch("fxdesk.live.feed.MT5Feed.available", return_value=False):
            feed = build_feed(self.config)
        self.assertIsInstance(feed, DataFeed)

    def test_build_feed_uses_mt4_bridge(self):
        def responder():
            deadline = time.time() + 2
            while time.time() < deadline:
                commands = list(self.directory.glob("cmd_*.txt"))
                if commands:
                    request_id = commands[0].stem[4:]
                    response = self.directory / f"res_{request_id}.txt"
                    response.write_text("OK=1\nMESSAGE=pong\n", encoding="ascii")
                    return
                time.sleep(0.005)

        thread = threading.Thread(target=responder, daemon=True)
        thread.start()
        with patch("fxdesk.live.feed.MT5Feed.available", return_value=False):
            feed = build_feed(self.config)
        thread.join(timeout=2)
        self.assertIsInstance(feed, MT4Feed)
        feed.close()

    def test_parse_helpers(self):
        parsed = _parse_kv("# comment\nOK=1\nBID = 1.1\n")
        self.assertEqual(parsed["OK"], "1")
        self.assertEqual(parsed["BID"], "1.1")
        self.assertEqual(_parse_time("2024.01.02 03:04:05").day, 2)
        self.assertIsNone(_parse_time("nonsense"))


if __name__ == "__main__":
    unittest.main()
