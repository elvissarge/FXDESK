"""Market-data service: provider fallback + local cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import pandas as pd

from fxdesk.data.base import DataProvider, empty_frame, to_utc
from fxdesk.data.cache import OHLCVCache, merge_frames
from fxdesk.data.providers import build_provider, provider_names
from fxdesk.errors import DataError, ProviderError
from fxdesk.timeframes import (
    is_intraday,
    normalize_timeframe,
    timeframe_minutes,
)


class DataService:
    def __init__(
        self,
        config: dict[str, Any],
        providers: Iterable[str] | None = None,
    ):
        self.config = config
        data_cfg = config.get("data", {})
        self.cache = OHLCVCache(data_cfg.get("cache_dir", "data_cache"))
        self._providers: dict[str, DataProvider] = {}
        self._allowed = set(providers) if providers else None

    def get_provider(self, name: str) -> DataProvider:
        if name not in self._providers:
            self._providers[name] = build_provider(name, self.config)
        return self._providers[name]

    def provider_order(self, timeframe: str) -> list[str]:
        tf = normalize_timeframe(timeframe)
        data_cfg = self.config.get("data", {})
        key = "provider_order_intraday" if is_intraday(tf) else "provider_order_daily"
        order = list(data_cfg.get(key) or [])
        for name in data_cfg.get("providers") or []:
            if name not in order:
                order.append(name)
        if self._allowed is not None:
            order = [name for name in order if name in self._allowed]
        return order

    def provider_status(self) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for name in provider_names():
            try:
                status[name] = self.get_provider(name).available()
            except Exception:
                status[name] = False
        return status

    def fetch(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        provider: str | None = None,
        refresh: bool = False,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        end_dt = to_utc(end) or datetime.now(timezone.utc)
        minutes = timeframe_minutes(tf)

        if start is None:
            bars = int(self.config.get("data", {}).get("max_bars", 20000))
            start_dt = end_dt - timedelta(minutes=minutes * bars)
        else:
            start_dt = to_utc(start)
            if start_dt is None:
                raise DataError("invalid start date")

        if start_dt >= end_dt:
            raise DataError(f"start ({start_dt}) must be before end ({end_dt})")

        names = [provider] if provider else self.provider_order(tf)
        errors: list[str] = []

        for name in names:
            try:
                data_provider = self.get_provider(name)
            except ProviderError as exc:
                errors.append(f"{name}: {exc}")
                continue

            if not data_provider.available():
                errors.append(f"{name}: unavailable")
                continue

            cached = None
            if use_cache:
                cached = self.cache.load(name, symbol, tf)

            if (
                cached is not None
                and not refresh
                and self._covers(cached, start_dt, end_dt, tf)
            ):
                return cached.loc[start_dt:end_dt].copy()

            fetch_start = start_dt
            if cached is not None and len(cached) and not refresh:
                overlap = timedelta(minutes=minutes * 2)
                # Only fetch the missing tail when the cache already reaches
                # back far enough. Otherwise we need the full requested range.
                if cached.index.min() <= start_dt + overlap:
                    candidate = cached.index.max() - overlap
                    if candidate > fetch_start:
                        fetch_start = candidate

            try:
                frame = data_provider.fetch(symbol, tf, fetch_start, end_dt)
                if frame is None or frame.empty:
                    errors.append(f"{name}: empty response")
                    continue
                frame = data_provider.normalize(frame, symbol, tf)
                if frame.empty:
                    errors.append(f"{name}: empty after normalisation")
                    continue
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue

            merged = merge_frames(cached, frame)
            if use_cache:
                self.cache.save(name, symbol, tf, merged)

            window = merged.loc[start_dt:end_dt]
            if window.empty:
                errors.append(f"{name}: no bars inside requested window")
                continue

            return window.copy()

        detail = "; ".join(errors) if errors else "no providers configured"
        raise DataError(f"could not load {symbol} {tf}: {detail}")

    def fetch_latest(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 500,
        provider: str | None = None,
        refresh: bool = True,
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        end = datetime.now(timezone.utc)
        minutes = timeframe_minutes(tf)
        lookback = max(bars * 2, bars + 300)
        start = end - timedelta(minutes=minutes * lookback)
        frame = self.fetch(
            symbol,
            tf,
            start=start,
            end=end,
            provider=provider,
            refresh=refresh,
        )
        return frame.tail(bars)

    def clear_cache(self) -> None:
        self.cache.clear()

    @staticmethod
    def _covers(
        frame: pd.DataFrame | None,
        start: datetime,
        end: datetime,
        timeframe: str,
    ) -> bool:
        if frame is None or frame.empty:
            return False
        step = timedelta(minutes=timeframe_minutes(timeframe))
        tolerance = max(step * 3, timedelta(days=1)) if step >= timedelta(days=1) else step * 3
        return frame.index.min() <= start + tolerance and frame.index.max() >= end - tolerance


__all__ = ["DataService", "empty_frame"]
