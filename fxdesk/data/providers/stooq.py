"""Stooq daily FX / index history (no API key)."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import base_symbol, clean_symbol
from fxdesk.timeframes import normalize_timeframe

_INDEX_MAP = {
    "US30": "^dji",
    "NAS100": "^ndq",
    "SPX500": "^spx",
    "GER40": "^dax",
    "UK100": "^ukx",
}


class StooqProvider(DataProvider):
    name = "stooq"
    supports_intraday = False
    URL = "https://stooq.com/q/d/l/"

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in ("1d", "1w"):
            raise ProviderError("stooq only serves daily/weekly candles")

        key = base_symbol(symbol)
        ticker = _INDEX_MAP.get(key, clean_symbol(symbol).lower())
        params: dict[str, str] = {"s": ticker, "i": "d"}
        if start:
            params["d1"] = start.strftime("%Y%m%d")
        if end:
            params["d2"] = end.strftime("%Y%m%d")

        try:
            response = requests.get(
                self.URL,
                params=params,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 fxdesk/0.1"},
            )
        except requests.RequestException as exc:
            raise ProviderError(f"stooq request failed: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(f"stooq HTTP {response.status_code}")

        text = response.text.strip()
        if not text or "Date,Open" not in text[:200]:
            raise ProviderError(f"stooq returned no data: {text[:120]!r}")

        try:
            raw = pd.read_csv(io.StringIO(text))
        except pd.errors.ParserError as exc:
            raise ProviderError(f"stooq CSV parse failed: {exc}") from exc

        raw.columns = [str(col).strip().lower() for col in raw.columns]
        if "date" not in raw.columns:
            raise ProviderError("stooq response has no Date column")

        raw["date"] = pd.to_datetime(raw["date"], utc=True, errors="coerce")
        raw = raw.dropna(subset=["date"]).set_index("date")
        frame = self.normalize(raw, symbol, tf)

        if tf == "1w":
            frame = self.resample(frame, "1w")

        return frame
