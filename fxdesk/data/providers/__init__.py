"""Data provider registry."""

from __future__ import annotations

from typing import Any

from fxdesk.data.base import DataProvider
from fxdesk.data.providers.alphavantage import AlphaVantageProvider
from fxdesk.data.providers.dukascopy import DukascopyProvider
from fxdesk.data.providers.frankfurter import FrankfurterProvider
from fxdesk.data.providers.mt5 import MT5Provider
from fxdesk.data.providers.stooq import StooqProvider
from fxdesk.data.providers.twelvedata import TwelveDataProvider
from fxdesk.data.providers.yahoo import YahooProvider
from fxdesk.errors import ProviderError

_REGISTRY: dict[str, type[DataProvider]] = {
    cls.name: cls
    for cls in (
        MT5Provider,
        TwelveDataProvider,
        AlphaVantageProvider,
        DukascopyProvider,
        StooqProvider,
        FrankfurterProvider,
        YahooProvider,
    )
}


def build_provider(name: str, config: dict[str, Any]) -> DataProvider:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderError(f"unknown data provider {name!r}")
    return cls(config)


def provider_names() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "build_provider",
    "provider_names",
    "DataProvider",
    "MT5Provider",
    "TwelveDataProvider",
    "AlphaVantageProvider",
    "DukascopyProvider",
    "StooqProvider",
    "FrankfurterProvider",
    "YahooProvider",
]
