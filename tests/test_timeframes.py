import unittest

from fxdesk.errors import ConfigError
from fxdesk.timeframes import (
    is_intraday,
    normalize_timeframe,
    pandas_rule,
    periods_per_year,
    supported_timeframes,
    timeframe_minutes,
)


class TimeframeTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_timeframe("60m"), "1h")
        self.assertEqual(normalize_timeframe("H4"), "4h")
        self.assertEqual(normalize_timeframe("daily"), "1d")
        self.assertEqual(normalize_timeframe("W1"), "1w")

    def test_minutes_and_rules(self):
        self.assertEqual(timeframe_minutes("4h"), 240)
        self.assertEqual(pandas_rule("1d"), "1D")
        self.assertTrue(is_intraday("1h"))
        self.assertFalse(is_intraday("1d"))
        self.assertGreater(periods_per_year("1h"), periods_per_year("1d"))

    def test_supported(self):
        self.assertIn("1m", supported_timeframes())
        self.assertIn("1w", supported_timeframes())

    def test_invalid(self):
        with self.assertRaises(ConfigError):
            normalize_timeframe("3h")


if __name__ == "__main__":
    unittest.main()
