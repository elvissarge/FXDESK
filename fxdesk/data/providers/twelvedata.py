"""Twelve Data forex/CFD candles. Requires TWELVEDATA_API_KEY."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import base_symbol, spec_for
from fxdesk.timeframes import normalize_timeframe

_INTERVALS = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1day",
    "1w": "1week",
}

_CFD_OVERRIDES = {
    "US30": "DJI",
    "NAS100": "NDX",
    "SPX500": "SPX",
    "GER40": "DAX",
    "UK100": "UKX",
    "USOIL": "WTI/USD",
    "UKOIL": "BRENT/USD",
}


def _td_symbol(symbol: str) -> str:
    key = base_symbol(symbol)
    if key in _CFD_OVERRIDES:
        return _CFD_OVERRIDES[key]
    spec = spec_for(symbol)
    return f"{spec.base}/{spec.quote}"


class TwelveDataProvider(DataProvider):
    name = "twelvedata"
    supports_intraday = True
    URL = "https://api.twelvedata.com/time_series"

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in _INTERVALS:
            raise ProviderError(f"twelvedata does not support {tf}")

        api_key = (self.config.get("data", {}).get("api_keys") or {}).get("twelvedata")
        if not api_key:
            raise ProviderError("TWELVEDATA_API_KEY is not configured")

        params = {
            "symbol": _td_symbol(symbol),
            "interval": _INTERVALS[tf],
            "apikey": api_key,
            "timezone": "UTC",
            "order": "ASC",
            "outputsize": 5000,
        }
        if start:
            params["start_date"] = start.strftime("%Y-%m-%d %H:%M:%S")
        if end:
            params["end_date"] = end.strftime("%Y-%m-%d %H:%M:%S")

        try:
            response = requests.get(self.URL, params=params, timeout=30)
        except requests.RequestException as exc:
            raise ProviderError(f"twelvedata request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"twelvedata HTTP {response.status_code}")

        payload = response.json()
        if payload.get("status") == "error" or "values" not in payload:
            message = payload.get("message") or payload.get("code") or "no values"
            raise ProviderError(f"twelvedata error: {message}")

        raw = pd.DataFrame(payload["values"])
        if "datetime" not in raw.columns:
            raise ProviderError("twelvedata response has no datetime column")

        raw["datetime"] = pd.to_datetime(raw["datetime"], utc=True, errors="coerce")
        raw = raw.dropna(subset=["datetime"]).set_index("datetime")
        frame = self.normalize(raw, symbol, tf)
        return frame
