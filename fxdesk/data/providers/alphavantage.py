"""Alpha Vantage FX history. Requires ALPHAVANTAGE_API_KEY."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import spec_for
from fxdesk.timeframes import normalize_timeframe

_INTRADAY = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "60min",
}


class AlphaVantageProvider(DataProvider):
    name = "alphavantage"
    supports_intraday = True
    URL = "https://www.alphavantage.co/query"

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        spec = spec_for(symbol)
        if spec.kind != "fx":
            raise ProviderError("alphavantage free FX endpoint only supports currency pairs")

        api_key = (self.config.get("data", {}).get("api_keys") or {}).get("alphavantage")
        if not api_key:
            raise ProviderError("ALPHAVANTAGE_API_KEY is not configured")

        if tf in _INTRADAY:
            function = "FX_INTRADAY"
            interval = _INTRADAY[tf]
        elif tf == "1d":
            function = "FX_DAILY"
            interval = None
        elif tf == "1w":
            function = "FX_WEEKLY"
            interval = None
        else:
            raise ProviderError(f"alphavantage does not support {tf}")

        params = {
            "function": function,
            "from_symbol": spec.base,
            "to_symbol": spec.quote,
            "apikey": api_key,
            "outputsize": "full",
        }
        if interval:
            params["interval"] = interval

        try:
            response = requests.get(self.URL, params=params, timeout=30)
        except requests.RequestException as exc:
            raise ProviderError(f"alphavantage request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"alphavantage HTTP {response.status_code}")

        payload = response.json()
        series_key = next(
            (key for key in payload if key.startswith("Time Series FX")), None
        )
        if series_key is None:
            message = (
                payload.get("Note")
                or payload.get("Information")
                or payload.get("Error Message")
                or "no time series returned"
            )
            raise ProviderError(f"alphavantage error: {message}")

        rows = []
        for stamp, values in payload[series_key].items():
            rows.append(
                {
                    "time": stamp,
                    "open": values.get("1. open"),
                    "high": values.get("2. high"),
                    "low": values.get("3. low"),
                    "close": values.get("4. close"),
                    "volume": 0.0,
                }
            )

        raw = pd.DataFrame(rows)
        frame = self.normalize(raw, symbol, tf)

        if start is not None:
            frame = frame[frame.index >= start]
        if end is not None:
            frame = frame[frame.index <= end]

        return frame
