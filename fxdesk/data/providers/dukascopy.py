"""Dukascopy free tick data (no API key), resampled to OHLCV.

Downloads hourly .bi5 tick files and aggregates them. This is ideal for
intraday history. Keep ranges modest because every hour is one HTTP request.
"""

from __future__ import annotations

import logging
import lzma
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.symbols import base_symbol, spec_for
from fxdesk.timeframes import normalize_timeframe, pandas_rule, timeframe_minutes

_RECORD = struct.Struct(">IIIff")
_DECIMALS = {"XAUUSD": 3, "XAGUSD": 3}
logger = logging.getLogger(__name__)


class DukascopyProvider(DataProvider):
    name = "dukascopy"
    supports_intraday = True
    BASE = "https://datafeed.dukascopy.com/datafeed"

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if timeframe_minutes(tf) >= 1440:
            raise ProviderError("dukascopy provider is for intraday timeframes")

        spec = spec_for(symbol)
        if spec.kind not in ("fx", "metal"):
            raise ProviderError("dukascopy instrument mapping is missing for this symbol")

        instrument = base_symbol(symbol)
        decimals = _DECIMALS.get(instrument, spec.digits)

        start = start.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        end = end.astimezone(timezone.utc)
        if end.minute or end.second or end.microsecond:
            end = end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

        max_days = int(self.config.get("data", {}).get("dukascopy_max_days", 45))
        if (end - start) > timedelta(days=max_days):
            capped = end - timedelta(days=max_days)
            logger.warning(
                "dukascopy capped range to %s days (%s..%s)",
                max_days,
                capped.date(),
                end.date(),
            )
            start = capped

        hours: list[datetime] = []
        cursor = start
        while cursor < end:
            hours.append(cursor)
            cursor += timedelta(hours=1)

        workers = int(self.config.get("data", {}).get("dukascopy_workers", 8))
        frames: list[pd.DataFrame] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {
                pool.submit(self._fetch_hour, instrument, hour, decimals): hour
                for hour in hours
            }
            for future in as_completed(futures):
                try:
                    frame = future.result()
                except Exception:
                    continue
                if frame is not None and len(frame):
                    frames.append(frame)

        if not frames:
            raise ProviderError("dukascopy returned no ticks for the requested range")

        ticks = pd.concat(frames).sort_index()
        ticks = ticks[~ticks.index.duplicated(keep="last")]

        rule = pandas_rule(tf)
        grouped = ticks.resample(rule, label="left", closed="left").agg(
            {
                "mid": ["first", "max", "min", "last"],
                "volume": "sum",
            }
        )
        grouped.columns = ["open", "high", "low", "close", "volume"]
        grouped = grouped.dropna(subset=["open", "high", "low", "close"])

        return self.normalize(grouped, symbol, tf)

    def _fetch_hour(
        self, instrument: str, hour: datetime, decimals: int
    ) -> pd.DataFrame | None:
        url = (
            f"{self.BASE}/{instrument}/{hour.year}/"
            f"{hour.month - 1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
        )
        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0 fxdesk/0.1"},
            )
        except requests.RequestException:
            return None

        if response.status_code == 404 or not response.content:
            return None
        if response.status_code != 200:
            return None

        try:
            raw = lzma.decompress(response.content, format=lzma.FORMAT_ALONE)
        except lzma.LZMAError:
            raw = response.content

        count = len(raw) // _RECORD.size
        if count == 0:
            return None

        factor = 10.0 ** decimals
        base_ms = int(hour.timestamp() * 1000)
        stamps: list[int] = []
        mids: list[float] = []
        volumes: list[float] = []

        for index in range(count):
            offset, ask, bid, ask_volume, bid_volume = _RECORD.unpack_from(
                raw, index * _RECORD.size
            )
            if ask <= 0 or bid <= 0:
                continue
            stamps.append(base_ms + int(offset))
            mids.append((ask + bid) / 2.0 / factor)
            volumes.append(float(ask_volume) + float(bid_volume))

        if not stamps:
            return None

        index = pd.to_datetime(stamps, unit="ms", utc=True)
        return pd.DataFrame({"mid": mids, "volume": volumes}, index=index)
