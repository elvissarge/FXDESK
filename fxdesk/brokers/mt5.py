"""Native MetaTrader 5 broker adapter (official package, Windows only).

Implements the same :class:`~fxdesk.brokers.base.Broker` interface as the paper
and MT4 adapters, so signals, risk sizing and the paper runner can talk to a
live MT5 terminal. Orders are market orders with optional SL/TP and use the
filling mode advertised by the broker symbol.

The adapter does not auto-execute anything by itself; the paper runner keeps
using the simulated broker. Call it explicitly from your own strategy code once
you have verified behaviour on a demo account.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fxdesk.brokers.base import (
    AccountInfo,
    Broker,
    OrderRequest,
    OrderResult,
    Position,
    Quote,
    SymbolInfo,
)
from fxdesk.errors import BrokerError
from fxdesk.symbols import spec_for

_FILLING_NAMES = {
    "fok": "ORDER_FILLING_FOK",
    "ioc": "ORDER_FILLING_IOC",
    "return": "ORDER_FILLING_RETURN",
}


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class MT5Broker(Broker):
    """Broker backed by the official ``MetaTrader5`` Python package."""

    name = "mt5"

    def __init__(self, config: dict[str, Any], module: Any | None = None):
        self.config = config
        self._mt5 = module
        cfg = config.get("mt5", {})
        self.symbol_suffix = str(cfg.get("symbol_suffix", "") or "")
        self.deviation = _int(cfg.get("deviation_points", 20), 20)
        self.magic = _int(cfg.get("magic", 20260101), 20260101)
        self.filling = str(cfg.get("filling", "auto") or "auto").lower()

    # ------------------------------------------------------------- lifecycle
    def available(self) -> bool:
        if self._mt5 is not None:
            return True
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
            raise BrokerError(f"MetaTrader5 package is not installed: {exc}") from exc

        cfg = self.config.get("mt5", {})
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
            raise BrokerError(f"MT5 initialize failed: {mt5.last_error()}")

        self._mt5 = mt5
        return mt5

    def connect(self) -> None:
        self._module()

    def disconnect(self) -> None:
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            finally:
                self._mt5 = None

    # --------------------------------------------------------------- symbols
    def _broker_symbol(self, symbol: str) -> str:
        suffix = self.symbol_suffix
        if suffix and not symbol.endswith(suffix):
            return f"{symbol}{suffix}"
        return symbol

    def _strip_suffix(self, symbol: str) -> str:
        suffix = self.symbol_suffix
        if suffix and symbol.endswith(suffix):
            return symbol[: -len(suffix)]
        return symbol

    def _select(self, mt5, broker_symbol: str) -> None:
        if not mt5.symbol_select(broker_symbol, True):
            raise BrokerError(
                f"MT5 symbol {broker_symbol!r} not found: {mt5.last_error()}"
            )

    def account_info(self) -> AccountInfo:
        mt5 = self._module()
        info = mt5.account_info()
        if info is None:
            raise BrokerError(f"MT5 account_info failed: {mt5.last_error()}")
        return AccountInfo(
            balance=_num(_attr(info, "balance")),
            equity=_num(_attr(info, "equity")),
            currency=_attr(info, "currency", "USD") or "USD",
            leverage=_num(_attr(info, "leverage"), 1.0) or 1.0,
            margin_free=_num(_attr(info, "margin_free")),
            broker=_attr(info, "company", "MT5") or "MT5",
        )

    def symbol_info(self, symbol: str) -> SymbolInfo:
        mt5 = self._module()
        broker_symbol = self._broker_symbol(symbol)
        self._select(mt5, broker_symbol)
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            raise BrokerError(
                f"MT5 symbol_info failed for {broker_symbol}: {mt5.last_error()}"
            )
        spec = spec_for(symbol, self.config.get("symbols", {}))
        point = _num(_attr(info, "point"), spec.pip_size) or spec.pip_size
        return SymbolInfo(
            symbol=symbol,
            digits=_int(_attr(info, "digits"), spec.digits),
            pip_size=spec.pip_size,
            contract_size=_num(_attr(info, "trade_contract_size"), spec.contract_size)
            or spec.contract_size,
            min_lot=_num(_attr(info, "volume_min"), 0.01) or 0.01,
            lot_step=_num(_attr(info, "volume_step"), 0.01) or 0.01,
            max_lot=_num(_attr(info, "volume_max"), 50.0) or 50.0,
            spread=_num(_attr(info, "spread")) * point,
        )

    # ----------------------------------------------------------------- quote
    def quote(self, symbol: str) -> Quote:
        mt5 = self._module()
        broker_symbol = self._broker_symbol(symbol)
        self._select(mt5, broker_symbol)
        tick = mt5.symbol_info_tick(broker_symbol)
        bid = _num(_attr(tick, "bid"))
        ask = _num(_attr(tick, "ask"))
        if tick is None or bid <= 0 or ask <= 0:
            raise BrokerError(
                f"MT5 returned no quote for {broker_symbol}: {mt5.last_error()}"
            )
        stamp = _int(_attr(tick, "time"))
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            time=datetime.fromtimestamp(stamp, timezone.utc) if stamp else None,
        )

    # ----------------------------------------------------------------- orders
    def _filling_type(self, mt5, broker_symbol: str) -> int:
        if self.filling in _FILLING_NAMES:
            return _int(
                _attr(mt5, _FILLING_NAMES[self.filling]),
                _int(_attr(mt5, "ORDER_FILLING_IOC", 1), 1),
            )
        info = mt5.symbol_info(broker_symbol)
        mode = _int(_attr(info, "filling_mode"), 0)
        if mode == 0:
            return _int(_attr(mt5, "ORDER_FILLING_IOC", 1), 1)
        if mode & _int(_attr(mt5, "SYMBOL_FILLING_FOK", 1), 1):
            return _int(_attr(mt5, "ORDER_FILLING_FOK", 0), 0)
        if mode & _int(_attr(mt5, "SYMBOL_FILLING_IOC", 2), 2):
            return _int(_attr(mt5, "ORDER_FILLING_IOC", 1), 1)
        return _int(_attr(mt5, "ORDER_FILLING_RETURN", 2), 2)

    def _send(self, mt5, payload: dict[str, Any]) -> tuple[Any | None, str]:
        result = mt5.order_send(payload)
        if result is None:
            return None, f"MT5 order_send failed: {mt5.last_error()}"
        retcode = _int(_attr(result, "retcode"))
        ok_codes = {
            _int(_attr(mt5, "TRADE_RETCODE_DONE", 10009), 10009),
            _int(_attr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010), 10010),
            _int(_attr(mt5, "TRADE_RETCODE_PLACED", 10008), 10008),
        }
        if retcode in ok_codes:
            return result, ""
        message = str(_attr(result, "comment", "") or f"retcode {retcode}")
        return result, message

    def place_order(self, request: OrderRequest) -> OrderResult:
        side = request.side.lower()
        if side not in ("buy", "sell"):
            return OrderResult(False, message=f"invalid side {request.side!r}")
        if request.volume <= 0:
            return OrderResult(False, message="volume must be positive")

        try:
            mt5 = self._module()
            broker_symbol = self._broker_symbol(request.symbol)
            self._select(mt5, broker_symbol)
            tick = mt5.symbol_info_tick(broker_symbol)
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        if tick is None:
            return OrderResult(
                False, message=f"MT5 returned no tick for {broker_symbol}"
            )

        order_type = (
            _int(_attr(mt5, "ORDER_TYPE_BUY", 0), 0)
            if side == "buy"
            else _int(_attr(mt5, "ORDER_TYPE_SELL", 1), 1)
        )
        price = _num(_attr(tick, "ask" if side == "buy" else "bid"))

        payload: dict[str, Any] = {
            "action": _int(_attr(mt5, "TRADE_ACTION_DEAL", 1), 1),
            "symbol": broker_symbol,
            "volume": float(request.volume),
            "type": order_type,
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": request.comment,
            "type_time": _int(_attr(mt5, "ORDER_TIME_GTC", 0), 0),
            "type_filling": self._filling_type(mt5, broker_symbol),
        }
        if request.stop_loss:
            payload["sl"] = float(request.stop_loss)
        if request.take_profit:
            payload["tp"] = float(request.take_profit)

        result, error = self._send(mt5, payload)
        if result is None:
            return OrderResult(False, message=error)

        ticket = (
            _int(_attr(result, "order"))
            or _int(_attr(result, "deal"))
            or None
        )
        return OrderResult(
            not error,
            ticket=ticket,
            price=_num(_attr(result, "price"), price) or price,
            message=error or str(_attr(result, "comment", "") or ""),
            retcode=_int(_attr(result, "retcode")),
        )

    def positions(self) -> list[Position]:
        mt5 = self._module()
        raw = mt5.positions_get()
        if not raw:
            return []

        buy_type = _int(_attr(mt5, "POSITION_TYPE_BUY", 0), 0)
        result: list[Position] = []
        for item in raw:
            side = "buy" if _int(_attr(item, "type")) == buy_type else "sell"
            stamp = _int(_attr(item, "time"))
            result.append(
                Position(
                    ticket=_int(_attr(item, "ticket")),
                    symbol=self._strip_suffix(str(_attr(item, "symbol", ""))),
                    side=side,
                    volume=_num(_attr(item, "volume")),
                    entry=_num(_attr(item, "price_open")),
                    stop_loss=_num(_attr(item, "sl")) or None,
                    take_profit=_num(_attr(item, "tp")) or None,
                    opened_at=datetime.fromtimestamp(stamp, timezone.utc)
                    if stamp
                    else datetime.now(timezone.utc),
                    profit=_num(_attr(item, "profit")),
                    comment=str(_attr(item, "comment", "") or ""),
                )
            )
        return result

    def close_position(self, ticket: int) -> OrderResult:
        try:
            mt5 = self._module()
            raw = mt5.positions_get(ticket=int(ticket))
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        if not raw:
            return OrderResult(False, message=f"MT5 position {ticket} not found")

        item = raw[0]
        broker_symbol = str(_attr(item, "symbol", ""))
        try:
            self._select(mt5, broker_symbol)
            tick = mt5.symbol_info_tick(broker_symbol)
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        if tick is None:
            return OrderResult(
                False, message=f"MT5 returned no tick for {broker_symbol}"
            )

        position_is_buy = _int(_attr(item, "type")) == _int(
            _attr(mt5, "POSITION_TYPE_BUY", 0), 0
        )
        order_type = (
            _int(_attr(mt5, "ORDER_TYPE_SELL", 1), 1)
            if position_is_buy
            else _int(_attr(mt5, "ORDER_TYPE_BUY", 0), 0)
        )
        price = _num(_attr(tick, "bid" if position_is_buy else "ask"))

        payload: dict[str, Any] = {
            "action": _int(_attr(mt5, "TRADE_ACTION_DEAL", 1), 1),
            "symbol": broker_symbol,
            "volume": _num(_attr(item, "volume")),
            "type": order_type,
            "position": int(ticket),
            "price": price,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "fxdesk close",
            "type_time": _int(_attr(mt5, "ORDER_TIME_GTC", 0), 0),
            "type_filling": self._filling_type(mt5, broker_symbol),
        }

        result, error = self._send(mt5, payload)
        if result is None:
            return OrderResult(False, message=error)

        return OrderResult(
            not error,
            ticket=int(ticket),
            price=_num(_attr(result, "price"), price) or price,
            message=error or "closed",
            retcode=_int(_attr(result, "retcode")),
        )
