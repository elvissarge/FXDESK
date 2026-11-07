import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from argparse import Namespace
from pathlib import Path

from fxdesk.cli import _hoist_common, cmd_mt4, main
from fxdesk.config import load_config


class MT4CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.config = load_config()
        self.config["mt4"].update(
            {
                "bridge_dir": str(self.directory),
                "timeout_seconds": 1.0,
                "poll_interval_seconds": 0.01,
            }
        )

    def tearDown(self):
        self.temp.cleanup()

    def _respond_quote(self):
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
        return thread

    def test_mt4_quote_json(self):
        thread = self._respond_quote()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cmd_mt4(
                Namespace(mt4_command="quote", symbol="EURUSD", json=True),
                self.config,
            )
        thread.join(timeout=2)

        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["symbol"], "EURUSD")
        self.assertAlmostEqual(payload["bid"], 1.10)
        self.assertAlmostEqual(payload["ask"], 1.10002)

    def test_mt4_missing_bridge(self):
        self.config["mt4"]["bridge_dir"] = str(self.directory / "missing")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = cmd_mt4(
                Namespace(mt4_command="quote", symbol="EURUSD", json=False),
                self.config,
            )

        self.assertEqual(code, 1)
        self.assertIn("does not exist", error.getvalue())

    def test_hoist_common_options(self):
        argv = ["backtest", "--config", "x.yaml", "-v", "--symbol", "EURUSD"]
        self.assertEqual(
            _hoist_common(argv),
            ["--config", "x.yaml", "-v", "backtest", "--symbol", "EURUSD"],
        )

    def test_config_after_subcommand(self):
        missing = self.directory / "missing.yaml"
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = main(["symbols", "--config", str(missing)])
        self.assertEqual(code, 2)
        self.assertIn("config file not found", error.getvalue())


if __name__ == "__main__":
    unittest.main()
