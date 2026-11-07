"""Frankfurter / ECB daily reference rates (no API key).

Only daily closes are available, so OHLC is synthesised from the close.
Use this as a no-key fallback for daily FX history.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import spec_for
from fxdesk.timeframes import normalize_timeframe


class FrankfurterProvider(DataProvider):
    name = "frankfurter"
    supports_intraday = False
    URL = "https://api.frankfurter.app"

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in ("1d", "1w"):
            raise ProviderError("frankfurter only serves daily/weekly data")

        spec = spec_for(symbol)
        if spec.kind != "fx":
            raise ProviderError("frankfurter only supports fiat currency pairs")

        url = f"{self.URL}/{start:%Y-%m-%d}..{end:%Y-%m-%d}"
        try:
            response = requests.get(
                url,
                params={"from": spec.base, "to": spec.quote},
                timeout=30,
                headers={"User-Agent": "fxdesk/0.1"},
            )
        except requests.RequestException as exc:
            raise ProviderError(f"frankfurter request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"frankfurter HTTP {response.status_code}")

        payload = response.json()
        rates = payload.get("rates") or {}
        if not rates:
            raise ProviderError("frankfurter returned no rates")

        closes: dict[pd.Timestamp, float] = {}
        for day, mapping in rates.items():
            if spec.quote in mapping:
                closes[pd.Timestamp(day, tz="UTC")] = float(mapping[spec.quote])

        if not closes:
            raise ProviderError(f"frankfurter has no {spec.quote} rates")

        series = pd.Series(closes, dtype="float64").sort_index()
        frame = pd.DataFrame(
            {
                "open": series,
                "high": series,
                "low": series,
                "close": series,
                "volume": 0.0,
            }
        )
        frame = self.normalize(frame, symbol, tf)

        if tf == "1w":
            frame = self.resample(frame, "1w")

        return frame
