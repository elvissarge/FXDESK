import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fxdesk.config import deep_merge, load_config


class ConfigTests(unittest.TestCase):
    def test_deep_merge_preserves_defaults(self):
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"c": 9}, "e": 4}
        merged = deep_merge(base, override)
        self.assertEqual(merged["a"]["b"], 1)
        self.assertEqual(merged["a"]["c"], 9)
        self.assertEqual(merged["d"], 3)
        self.assertEqual(merged["e"], 4)

    def test_env_expansion_and_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text(
                "data:\n"
                "  api_keys:\n"
                "    twelvedata: ${TD_KEY}\n"
                "    alphavantage: ${AV_KEY:-fallback}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"TD_KEY": "secret"}, clear=False):
                os.environ.pop("AV_KEY", None)
                config = load_config(path)

        self.assertEqual(config["data"]["api_keys"]["twelvedata"], "secret")
        self.assertEqual(config["data"]["api_keys"]["alphavantage"], "fallback")
        self.assertEqual(config["account"]["currency"], "USD")
        self.assertIn("trend_ma", config["strategies"])


if __name__ == "__main__":
    unittest.main()
