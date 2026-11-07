import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from fxdesk.data.base import DataProvider
from fxdesk.data.providers.frankfurter import FrankfurterProvider
from fxdesk.data.providers.yahoo import YahooProvider
from fxdesk.errors import ProviderError


class DummyProvider(DataProvider):
    name = "dummy"

    def fetch(self, symbol, timeframe, start, end):
        return self.normalize(pd.DataFrame(), symbol, timeframe)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class ProviderTests(unittest.TestCase):
    def test_normalize_dedupes_and_sorts(self):
        provider = DummyProvider({})
        index = pd.to_datetime(
            ["2024-01-02", "2024-01-01", "2024-01-02"], utc=True
        )
        raw = pd.DataFrame(
            {
                "open": [1.2, 1.0, 1.3],
                "high": [1.3, 1.1, 1.4],
                "low": [1.1, 0.9, 1.2],
                "close": [1.25, 1.05, 1.35],
            },
            index=index,
        )
        clean = provider.normalize(raw, "EURUSD", "1d")
        self.assertEqual(len(clean), 2)
        self.assertTrue(clean.index.is_monotonic_increasing)
        self.assertAlmostEqual(clean["close"].iloc[-1], 1.35)
        self.assertTrue((clean["volume"] == 0.0).all())

    def test_frankfurter_daily_parse(self):
        payload = {
            "amount": 1.0,
            "base": "EUR",
            "rates": {
                "2024-01-02": {"USD": 1.10},
                "2024-01-03": {"USD": 1.12},
            },
        }
        provider = FrankfurterProvider({})
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)

        with patch(
            "fxdesk.data.providers.frankfurter.requests.get",
            return_value=FakeResponse(payload),
        ):
            frame = provider.fetch("EURUSD", "1d", start, end)

        self.assertEqual(len(frame), 2)
        self.assertAlmostEqual(frame["close"].iloc[0], 1.10)
        self.assertAlmostEqual(frame["close"].iloc[-1], 1.12)
        self.assertTrue((frame["high"] == frame["close"]).all())

    def test_frankfurter_rejects_intraday(self):
        provider = FrankfurterProvider({})
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)
        with self.assertRaises(ProviderError):
            provider.fetch("EURUSD", "1h", start, end)

    def test_yahoo_resamples_hourly_to_four_hour(self):
        start = pd.Timestamp("2024-01-01", tz="UTC")
        timestamps = [
            int((start + pd.Timedelta(hours=i)).timestamp()) for i in range(8)
        ]
        closes = [1.10 + i * 0.0001 for i in range(8)]
        quotes = {
            "open": closes,
            "high": [value + 0.0002 for value in closes],
            "low": [value - 0.0002 for value in closes],
            "close": closes,
            "volume": [100] * 8,
        }
        payload = {
            "chart": {
                "result": [
                    {
                        "timestamp": timestamps,
                        "indicators": {"quote": [quotes]},
                    }
                ],
                "error": None,
            }
        }
        provider = YahooProvider({})
        with patch(
            "fxdesk.data.providers.yahoo.requests.get",
            return_value=FakeResponse(payload),
        ):
            frame = provider.fetch(
                "EURUSD",
                "4h",
                start.to_pydatetime(),
                (start + pd.Timedelta(days=1)).to_pydatetime(),
            )

        self.assertEqual(len(frame), 2)
        self.assertAlmostEqual(frame["high"].iloc[0], max(quotes["high"][:4]))
        self.assertAlmostEqual(frame["low"].iloc[0], min(quotes["low"][:4]))

    def test_frankfurter_http_error(self):
        provider = FrankfurterProvider({})
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)
        with patch(
            "fxdesk.data.providers.frankfurter.requests.get",
            return_value=FakeResponse({}, status_code=500),
        ):
            with self.assertRaises(ProviderError):
                provider.fetch("EURUSD", "1d", start, end)


if __name__ == "__main__":
    unittest.main()
