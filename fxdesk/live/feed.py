"""Live quote feeds: MT5 native, or REST/cached data fallback."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from fxdesk.brokers.base import Quote
from fxdesk.data import DataService
from fxdesk.data.providers.mt5 import _TIMEFRAMES
from fxdesk.errors import BrokerError, ProviderError
from fxdesk.symbols import spec_for
from fxdesk.timeframes import normalize_timeframe, timeframe_minutes

logger = logging.getLogger(__name__)


class QuoteFeed(ABC):
    @abstractmethod
    def get_quote(self, symbol: str) -> Quote:
        ...

    def get_bars(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        raise NotImplementedError

    def close(self) -> None:
        return None


class DataFeed(QuoteFeed):
    """Derives a bid/ask quote from the latest candle plus a configured spread."""

    def __init__(
        self,
        config: dict[str, Any],
        data: DataService | None = None,
        quote_timeframe: str | None = None,
    ):
        self.config = config
        self.data = data or DataService(config)
        paper_cfg = config.get("paper", {})
        self.quote_timeframe = normalize_timeframe(
            quote_timeframe or paper_cfg.get("quote_timeframe", "1m")
        )
        self.spread_pips = float(
            paper_cfg.get(
                "spread_pips",
                config.get("backtest", {}).get("spread_pips", 1.0),
            )
        )

    def get_quote(self, symbol: str) -> Quote:
        spec = spec_for(symbol, self.config.get("symbols", {}))
        frame = None
        last_error: Exception | None = None

        for timeframe in (self.quote_timeframe, "5m", "1h", "1d"):
            try:
                frame = self.data.fetch_latest(
                    symbol, timeframe, bars=3, refresh=True
                )
                if frame is not None and len(frame):
                    break
            except Exception as exc:
                last_error = exc
                frame = None

        if frame is None or frame.empty:
            raise BrokerError(f"no quote available for {symbol}: {last_error}")

        mid = float(frame["close"].iloc[-1])
        half = self.spread_pips / 2.0 * spec.pip_size
        return Quote(
            symbol=symbol,
            bid=mid - half,
            ask=mid + half,
            time=frame.index[-1].to_pydatetime(),
        )

    def get_bars(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        return self.data.fetch_latest(symbol, timeframe, bars=bars, refresh=True)


class MT4Feed(QuoteFeed):
    """Live quotes from the MT4 file bridge, with REST data for candles."""

    name = "mt4"

    def __init__(self, config: dict[str, Any], data: DataService | None = None):
        from fxdesk.brokers.mt4 import MT4FileBridgeBroker

        self.config = config
        self.data = data or DataService(config)
        self.broker = MT4FileBridgeBroker(config)
        if not self.broker.available():
            raise BrokerError(
                f"MT4 bridge is not configured at {self.broker.bridge_dir}"
            )
        self.broker.connect()

    def get_quote(self, symbol: str) -> Quote:
        return self.broker.quote(symbol)

    def get_bars(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        return self.data.fetch_latest(symbol, timeframe, bars=bars, refresh=True)

    def close(self) -> None:
        self.broker.disconnect()


class MT5Feed(QuoteFeed):
    name = "mt5"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        try:
            import MetaTrader5 as mt5
        except Exception as exc:  # pragma: no cover
            raise ProviderError(f"MetaTrader5 is not installed: {exc}") from exc

        cfg = config.get("mt5", {})
        kwargs: dict[str, Any] = {}
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

        self.mt5 = mt5
        self.suffix = cfg.get("symbol_suffix") or ""

    @staticmethod
    def available() -> bool:
        try:
            import MetaTrader5  # noqa: F401
        except Exception:
            return False
        return True

    def _broker_symbol(self, symbol: str) -> str:
        return f"{symbol}{self.suffix}"

    def get_quote(self, symbol: str) -> Quote:
        broker_symbol = self._broker_symbol(symbol)
        self.mt5.symbol_select(broker_symbol, True)
        tick = self.mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise BrokerError(f"MT5 has no tick for {broker_symbol}")
        return Quote(
            symbol=symbol,
            bid=float(tick.bid),
            ask=float(tick.ask),
            time=datetime.fromtimestamp(tick.time, timezone.utc),
        )

    def get_bars(self, symbol: str, timeframe: str, bars: int) -> pd.DataFrame:
        tf = normalize_timeframe(timeframe)
        if tf not in _TIMEFRAMES:
            raise ProviderError(f"MT5 does not support {tf}")

        broker_symbol = self._broker_symbol(symbol)
        self.mt5.symbol_select(broker_symbol, True)
        tf_const = getattr(self.mt5, _TIMEFRAMES[tf])
        rates = self.mt5.copy_rates_from_pos(broker_symbol, tf_const, 0, int(bars))
        if rates is None or len(rates) == 0:
            raise ProviderError(
                f"MT5 returned no rates for {broker_symbol} {tf}: {self.mt5.last_error()}"
            )

        frame = pd.DataFrame(rates)
        frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
        frame = frame.rename(columns={"tick_volume": "volume"})
        frame = frame.set_index("time")
        return frame[["open", "high", "low", "close", "volume"]].astype("float64")

    def close(self) -> None:
        try:
            self.mt5.shutdown()
        except Exception:
            pass


def build_feed(config: dict[str, Any], data: DataService | None = None) -> QuoteFeed:
    if MT5Feed.available():
        try:
            logger.info("using MetaTrader 5 live feed")
            return MT5Feed(config)
        except Exception as exc:
            logger.warning("MT5 feed unavailable (%s); trying MT4/REST", exc)

    try:
        feed = MT4Feed(config, data=data)
        logger.info("using MetaTrader 4 file-bridge feed")
        return feed
    except Exception as exc:
        logger.debug("MT4 feed unavailable: %s", exc)

    logger.info("using REST/cached data feed")
    return DataFeed(config, data=data)
