"""Yahoo Finance chart API provider (no API key, no extra dependency)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from urllib.parse import quote as url_quote

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import base_symbol, spec_for
from fxdesk.timeframes import normalize_timeframe

logger = logging.getLogger(__name__)

_INTERVALS = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "1h",
    "4h": "1h",
    "8h": "1h",
    "1d": "1d",
    "1w": "1wk",
}

_MAX_LOOKBACK_DAYS = {
    "1m": 7,
    "5m": 59,
    "15m": 59,
    "30m": 59,
    "1h": 729,
    "2h": 729,
    "4h": 729,
    "8h": 729,
    "1d": 20000,
    "1w": 20000,
}

_OVERRIDES = {
    "US30": "^DJI",
    "NAS100": "^NDX",
    "SPX500": "^GSPC",
    "GER40": "^GDAXI",
    "UK100": "^FTSE",
    "XAUUSD": "GC=F",
    "XAGUSD": "SI=F",
    "USOIL": "CL=F",
    "UKOIL": "BZ=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}


def _yahoo_symbol(symbol: str) -> str:
    key = base_symbol(symbol)
    if key in _OVERRIDES:
        return _OVERRIDES[key]
    spec = spec_for(symbol)
    if spec.kind == "fx":
        return f"{spec.base}{spec.quote}=X"
    return key


class YahooProvider(DataProvider):
    name = "yahoo"
    supports_intraday = True
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    def available(self) -> bool:
        return True

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in _INTERVALS:
            raise ProviderError(f"yahoo does not support {tf}")

        max_days = _MAX_LOOKBACK_DAYS[tf]
        if (end - start) > timedelta(days=max_days):
            capped = end - timedelta(days=max_days)
            logger.warning(
                "yahoo capped range to %s days for %s", max_days, tf
            )
            start = capped

        ticker = _yahoo_symbol(symbol)
        url = self.URL.format(symbol=url_quote(ticker, safe=""))
        params = {
            "period1": int(start.timestamp()),
            "period2": int(end.timestamp()),
            "interval": _INTERVALS[tf],
            "events": "div,splits",
            "includeAdjustedClose": "true",
        }

        try:
            response = requests.get(
                url,
                params=params,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 fxdesk/0.1"},
            )
        except requests.RequestException as exc:
            raise ProviderError(f"yahoo request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"yahoo HTTP {response.status_code}")

        payload = response.json()
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise ProviderError(f"yahoo error: {chart['error']}")

        results = chart.get("result") or []
        if not results:
            raise ProviderError(f"yahoo returned no data for {ticker}")

        result = results[0]
        timestamps = result.get("timestamp") or []
        if not timestamps:
            raise ProviderError(f"yahoo returned no timestamps for {ticker}")

        quotes = result.get("indicators", {}).get("quote") or [{}]
        quote_data = quotes[0]

        raw = pd.DataFrame(
            {
                "time": pd.to_datetime(timestamps, unit="s", utc=True),
                "open": quote_data.get("open"),
                "high": quote_data.get("high"),
                "low": quote_data.get("low"),
                "close": quote_data.get("close"),
                "volume": quote_data.get("volume"),
            }
        )
        raw = raw.dropna(subset=["open", "high", "low", "close"])
        raw = raw.set_index("time")
        frame = self.normalize(raw, symbol, tf)
        if tf in ("2h", "4h", "8h"):
            frame = self.resample(frame, tf)
        return frame
