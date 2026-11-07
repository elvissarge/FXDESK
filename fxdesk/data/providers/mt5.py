"""MetaTrader 5 candle provider (official Python package, Windows only)."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from fxdesk.data.base import DataProvider
from fxdesk.errors import ProviderError
from fxdesk.timeframes import normalize_timeframe

_TIMEFRAMES = {
    "1m": "TIMEFRAME_M1",
    "5m": "TIMEFRAME_M5",
    "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30",
    "1h": "TIMEFRAME_H1",
    "2h": "TIMEFRAME_H2",
    "4h": "TIMEFRAME_H4",
    "8h": "TIMEFRAME_H8",
    "1d": "TIMEFRAME_D1",
    "1w": "TIMEFRAME_W1",
}


class MT5Provider(DataProvider):
    name = "mt5"
    supports_intraday = True

    def __init__(self, config):
        super().__init__(config)
        self._mt5 = None

    def available(self) -> bool:
        try:
            import MetaTrader5  # noqa: F401
        except Exception:
            return False
        return True

    def _module(self):
        if self._mt5 is not None:
            return self._mt5

        try:
            import MetaTrader5 as mt5
        except Exception as exc:  # pragma: no cover - depends on host
            raise ProviderError(f"MetaTrader5 package is not installed: {exc}") from exc

        cfg = self.config.get("mt5", {})
        kwargs: dict = {}
        if cfg.get("path"):
            kwargs["path"] = cfg["path"]
        if cfg.get("login"):
            kwargs["login"] = int(cfg["login"])
        if cfg.get("password"):
            kwargs["password"] = cfg["password"]
        if cfg.get("server"):
            kwargs["server"] = cfg["server"]
        if cfg.get("timeout_ms"):
            kwargs["timeout"] = int(cfg["timeout_ms"])

        if not mt5.initialize(**kwargs):
            raise ProviderError(f"MT5 initialize failed: {mt5.last_error()}")

        self._mt5 = mt5
        return mt5

    def fetch(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in _TIMEFRAMES:
            raise ProviderError(f"MT5 does not support {tf}")

        mt5 = self._module()
        suffix = self.config.get("mt5", {}).get("symbol_suffix") or ""
        broker_symbol = f"{symbol}{suffix}"

        if not mt5.symbol_select(broker_symbol, True):
            raise ProviderError(
                f"MT5 symbol {broker_symbol!r} not found: {mt5.last_error()}"
            )

        tf_const = getattr(mt5, _TIMEFRAMES[tf])
        rates = mt5.copy_rates_range(broker_symbol, tf_const, start, end)
        if rates is None or len(rates) == 0:
            raise ProviderError(
                f"MT5 returned no rates for {broker_symbol} {tf}: {mt5.last_error()}"
            )

        raw = pd.DataFrame(rates)
        raw["time"] = pd.to_datetime(raw["time"], unit="s", utc=True)
        raw = raw.rename(columns={"tick_volume": "volume"})
        raw = raw.set_index("time")
        return self.normalize(raw, symbol, tf)

    def close(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            finally:
                self._mt5 = None
