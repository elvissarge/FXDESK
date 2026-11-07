"""Broker adapters."""

from fxdesk.brokers.base import (
    AccountInfo,
    Broker,
    ClosedTrade,
    OrderRequest,
    OrderResult,
    Position,
    Quote,
    SymbolInfo,
)
from fxdesk.brokers.mt4 import MT4FileBridgeBroker
from fxdesk.brokers.mt5 import MT5Broker
from fxdesk.brokers.paper import PaperBroker

__all__ = [
    "AccountInfo",
    "Broker",
    "ClosedTrade",
    "MT4FileBridgeBroker",
    "MT5Broker",
    "OrderRequest",
    "OrderResult",
    "PaperBroker",
    "Position",
    "Quote",
    "SymbolInfo",
]
