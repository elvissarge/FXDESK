"""Broker interfaces shared by paper, MT4 and MT5 adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AccountInfo:
    balance: float
    equity: float
    currency: str = "USD"
    leverage: float = 1.0
    margin_free: float = 0.0
    broker: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "currency": self.currency,
            "leverage": self.leverage,
            "margin_free": round(self.margin_free, 2),
            "broker": self.broker,
        }


@dataclass
class SymbolInfo:
    symbol: str
    digits: int
    pip_size: float
    contract_size: float
    min_lot: float
    lot_step: float
    max_lot: float
    spread: float = 0.0


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    time: datetime | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return max(self.ask - self.bid, 0.0)


@dataclass
class OrderRequest:
    symbol: str
    side: str  # "buy" or "sell"
    volume: float
    stop_loss: float | None = None
    take_profit: float | None = None
    comment: str = "fxdesk"


@dataclass
class OrderResult:
    ok: bool
    ticket: int | None = None
    price: float | None = None
    message: str = ""
    retcode: int | None = None


@dataclass
class Position:
    ticket: int
    symbol: str
    side: str
    volume: float
    entry: float
    stop_loss: float | None
    take_profit: float | None
    opened_at: datetime
    profit: float = 0.0
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at.isoformat(),
            "profit": round(self.profit, 2),
            "comment": self.comment,
        }


@dataclass
class ClosedTrade:
    ticket: int
    symbol: str
    side: str
    volume: float
    entry: float
    exit: float
    profit: float
    opened_at: datetime
    closed_at: datetime
    reason: str = ""
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "side": self.side,
            "volume": self.volume,
            "entry": self.entry,
            "exit": self.exit,
            "profit": round(self.profit, 2),
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat(),
            "reason": self.reason,
            "comment": self.comment,
        }


class Broker(ABC):
    name = "base"

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    @abstractmethod
    def account_info(self) -> AccountInfo:
        ...

    @abstractmethod
    def symbol_info(self, symbol: str) -> SymbolInfo:
        ...

    @abstractmethod
    def quote(self, symbol: str) -> Quote:
        ...

    @abstractmethod
    def place_order(self, request: OrderRequest) -> OrderResult:
        ...

    @abstractmethod
    def positions(self) -> list[Position]:
        ...

    def close_position(self, ticket: int) -> OrderResult:
        raise NotImplementedError(f"{self.name} does not support close_position")

    def close_all(self) -> list[OrderResult]:
        return [self.close_position(position.ticket) for position in self.positions()]
