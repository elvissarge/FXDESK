"""In-memory paper broker with SL/TP simulation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from fxdesk.errors import BrokerError
from fxdesk.symbols import pip_value_per_lot, spec_for


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, config: dict[str, Any], initial_balance: float | None = None):
        self.config = config
        paper_cfg = config.get("paper", {})
        account_cfg = config.get("account", {})

        self.currency = str(account_cfg.get("currency", "USD"))
        if initial_balance is not None:
            self.balance = float(initial_balance)
        else:
            self.balance = float(
                paper_cfg.get(
                    "initial_balance",
                    account_cfg.get("initial_balance", 10000.0),
                )
            )

        self.slippage_pips = float(paper_cfg.get("slippage_pips", 0.2))
        self.commission_per_lot = float(paper_cfg.get("commission_per_lot", 0.0))
        self.pip_value_rates = {
            str(key).upper(): float(value)
            for key, value in config.get("pip_value_rates", {}).items()
        }

        self.quotes: dict[str, Quote] = {}
        self._positions: dict[int, Position] = {}
        self._closed: list[ClosedTrade] = []
        self._next_ticket = 1
        self.realized_pnl = 0.0

    # ---------------------------------------------------------------- quotes
    def update_quote(self, quote: Quote) -> None:
        self.quotes[quote.symbol] = quote

    def update_price(
        self,
        symbol: str,
        bid: float,
        ask: float,
        time: datetime | None = None,
    ) -> None:
        self.update_quote(Quote(symbol=symbol, bid=float(bid), ask=float(ask), time=time))

    def quote(self, symbol: str) -> Quote:
        quote = self.quotes.get(symbol)
        if quote is None:
            raise BrokerError(f"paper broker has no quote for {symbol}")
        return quote

    # ---------------------------------------------------------------- account
    def symbol_info(self, symbol: str) -> SymbolInfo:
        spec = spec_for(symbol, self.config.get("symbols", {}))
        quote = self.quotes.get(symbol)
        spread = quote.spread if quote else 0.0
        risk = self.config.get("risk", {})
        return SymbolInfo(
            symbol=symbol,
            digits=spec.digits,
            pip_size=spec.pip_size,
            contract_size=spec.contract_size,
            min_lot=float(risk.get("min_lot", 0.01)),
            lot_step=float(risk.get("lot_step", 0.01)),
            max_lot=float(risk.get("max_lot", 50.0)),
            spread=spread,
        )

    def account_info(self) -> AccountInfo:
        unrealized = self.unrealized_pnl()
        equity = self.balance + unrealized
        return AccountInfo(
            balance=self.balance,
            equity=equity,
            currency=self.currency,
            leverage=1.0,
            margin_free=equity,
            broker="paper",
        )

    # ----------------------------------------------------------------- orders
    def place_order(self, request: OrderRequest) -> OrderResult:
        side = request.side.lower()
        if side not in ("buy", "sell"):
            return OrderResult(False, message=f"invalid side {request.side!r}")
        if request.volume <= 0:
            return OrderResult(False, message="volume must be positive")

        try:
            quote = self.quote(request.symbol)
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        spec = spec_for(request.symbol, self.config.get("symbols", {}))
        slip = spec.pip_size * self.slippage_pips
        price = quote.ask + slip if side == "buy" else quote.bid - slip

        ticket = self._next_ticket
        self._next_ticket += 1

        position = Position(
            ticket=ticket,
            symbol=request.symbol,
            side=side,
            volume=float(request.volume),
            entry=float(price),
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            opened_at=datetime.now(timezone.utc),
            profit=0.0,
            comment=request.comment,
        )
        self._positions[ticket] = position
        return OrderResult(True, ticket=ticket, price=price, message="filled")

    def close_position(
        self,
        ticket: int,
        price: float | None = None,
        reason: str = "manual",
    ) -> OrderResult:
        position = self._positions.pop(ticket, None)
        if position is None:
            return OrderResult(False, message=f"position {ticket} not found")

        if price is None:
            quote = self.quotes.get(position.symbol)
            if quote is None:
                self._positions[ticket] = position
                return OrderResult(False, message=f"no quote for {position.symbol}")
            price = quote.bid if position.side == "buy" else quote.ask

        profit = self._pnl(position, price) - self.commission_per_lot * position.volume
        self.balance += profit
        self.realized_pnl += profit

        closed = ClosedTrade(
            ticket=position.ticket,
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            entry=position.entry,
            exit=float(price),
            profit=profit,
            opened_at=position.opened_at,
            closed_at=datetime.now(timezone.utc),
            reason=reason,
            comment=position.comment,
        )
        self._closed.append(closed)
        return OrderResult(True, ticket=ticket, price=float(price), message=f"closed ({reason})")

    def process_quote(self, quote: Quote) -> list[ClosedTrade]:
        """Mark a quote and auto-close any SL/TP hit."""
        self.update_quote(quote)
        closed: list[ClosedTrade] = []

        for position in list(self._positions.values()):
            if position.symbol != quote.symbol:
                continue

            reason: str | None = None
            fill: float | None = None

            if position.side == "buy":
                if position.stop_loss is not None and quote.bid <= position.stop_loss:
                    reason, fill = "stop_loss", quote.bid
                elif position.take_profit is not None and quote.bid >= position.take_profit:
                    reason, fill = "take_profit", quote.bid
            else:
                if position.stop_loss is not None and quote.ask >= position.stop_loss:
                    reason, fill = "stop_loss", quote.ask
                elif position.take_profit is not None and quote.ask <= position.take_profit:
                    reason, fill = "take_profit", quote.ask

            if reason is not None:
                result = self.close_position(position.ticket, price=fill, reason=reason)
                if result.ok:
                    closed.append(self._closed[-1])

        return closed

    def positions(self) -> list[Position]:
        result: list[Position] = []
        for position in self._positions.values():
            quote = self.quotes.get(position.symbol)
            profit = 0.0
            if quote is not None:
                price = quote.bid if position.side == "buy" else quote.ask
                profit = self._pnl(position, price)
            result.append(replace(position, profit=profit))
        return result

    def closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed)

    def unrealized_pnl(self) -> float:
        total = 0.0
        for position in self._positions.values():
            quote = self.quotes.get(position.symbol)
            if quote is None:
                continue
            price = quote.bid if position.side == "buy" else quote.ask
            total += self._pnl(position, price)
        return total

    def _pnl(self, position: Position, price: float) -> float:
        spec = spec_for(position.symbol, self.config.get("symbols", {}))
        if spec.pip_size <= 0:
            return 0.0
        diff = (
            price - position.entry
            if position.side == "buy"
            else position.entry - price
        )
        rate = self.pip_value_rates.get(spec.quote.upper(), 1.0)
        pip_value = pip_value_per_lot(spec, price, self.currency, rate)
        return (diff / spec.pip_size) * pip_value * position.volume

    # ------------------------------------------------------------------ state
    def state_dict(self) -> dict[str, Any]:
        return {
            "balance": self.balance,
            "realized_pnl": self.realized_pnl,
            "next_ticket": self._next_ticket,
            "positions": [position.to_dict() for position in self._positions.values()],
            "closed": [trade.to_dict() for trade in self._closed],
        }

    def save_state(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.state_dict(), indent=2), encoding="utf-8")

    def load_state(self, path: str | Path) -> bool:
        target = Path(path)
        if not target.exists():
            return False

        data = json.loads(target.read_text(encoding="utf-8"))
        self.balance = float(data.get("balance", self.balance))
        self.realized_pnl = float(data.get("realized_pnl", 0.0))
        self._next_ticket = int(data.get("next_ticket", 1))

        self._positions = {}
        for item in data.get("positions", []):
            position = Position(
                ticket=int(item["ticket"]),
                symbol=item["symbol"],
                side=item["side"],
                volume=float(item["volume"]),
                entry=float(item["entry"]),
                stop_loss=item.get("stop_loss"),
                take_profit=item.get("take_profit"),
                opened_at=datetime.fromisoformat(item["opened_at"]),
                profit=float(item.get("profit", 0.0)),
                comment=item.get("comment", ""),
            )
            self._positions[position.ticket] = position

        self._closed = []
        for item in data.get("closed", []):
            self._closed.append(
                ClosedTrade(
                    ticket=int(item["ticket"]),
                    symbol=item["symbol"],
                    side=item["side"],
                    volume=float(item["volume"]),
                    entry=float(item["entry"]),
                    exit=float(item["exit"]),
                    profit=float(item["profit"]),
                    opened_at=datetime.fromisoformat(item["opened_at"]),
                    closed_at=datetime.fromisoformat(item["closed_at"]),
                    reason=item.get("reason", ""),
                    comment=item.get("comment", ""),
                )
            )
        return True

    def reset(self) -> None:
        self.quotes.clear()
        self._positions.clear()
        self._closed.clear()
        self._next_ticket = 1
        self.realized_pnl = 0.0
