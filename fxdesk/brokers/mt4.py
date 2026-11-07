"""File-based MetaTrader 4 bridge client.

The companion EA in ``bridge/FxDeskBridge.mq4`` polls a directory inside
``MQL4/Files`` for command files and writes response files. This keeps the
Python side broker-agnostic and avoids third-party DLLs.

Protocol
--------
Python writes ``cmd_<id>.txt``::

    ACTION=quote
    SYMBOL=EURUSD

The EA writes ``res_<id>.txt``::

    OK=1
    BID=1.10000
    ASK=1.10002
    TIME=2024.01.01 12:00:00

All values are ASCII ``KEY=VALUE`` lines. ``positions`` responses contain one
``POSITION=ticket|symbol|side|volume|entry|sl|tp|profit|comment|opened`` line
per open order.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
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


def _clean(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (
        "%Y.%m.%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y.%m.%d %H:%M",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _parse_kv(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip().upper()] = value.strip()
    return data


class MT4FileBridgeBroker(Broker):
    """Broker that talks to MetaTrader 4 through the file bridge EA."""

    name = "mt4"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        mt4 = config.get("mt4", {})
        raw_dir = mt4.get("bridge_dir") or "bridge/runtime"
        self.bridge_dir = Path(raw_dir).expanduser()
        self.timeout = float(mt4.get("timeout_seconds", 10.0))
        self.poll_interval = float(mt4.get("poll_interval_seconds", 0.05))
        self.symbol_suffix = str(mt4.get("symbol_suffix", "") or "")

    # ------------------------------------------------------------- lifecycle
    def available(self) -> bool:
        return self.bridge_dir.is_dir()

    def connect(self) -> None:
        self._request("ping")

    def disconnect(self) -> None:
        return None

    # --------------------------------------------------------------- symbols
    def _broker_symbol(self, symbol: str) -> str:
        suffix = self.symbol_suffix
        if suffix and not symbol.endswith(suffix):
            return f"{symbol}{suffix}"
        return symbol

    # --------------------------------------------------------------- request
    def _request(self, action: str, **fields: Any) -> dict[str, str]:
        if not self.bridge_dir:
            raise BrokerError("mt4.bridge_dir is not configured")
        if not self.bridge_dir.is_dir():
            raise BrokerError(
                f"MT4 bridge directory does not exist: {self.bridge_dir}. "
                "Create it under MQL4/Files and attach bridge/FxDeskBridge.mq4."
            )

        request_id = uuid.uuid4().hex[:12]
        cmd_path = self.bridge_dir / f"cmd_{request_id}.txt"
        res_path = self.bridge_dir / f"res_{request_id}.txt"

        lines = [f"ACTION={action}"]
        for key, value in fields.items():
            if value is None:
                continue
            lines.append(f"{key.upper()}={_clean(value)}")

        temp_path = self.bridge_dir / f".cmd_{request_id}.tmp"
        temp_path.write_text("\n".join(lines) + "\n", encoding="ascii", errors="replace")
        os.replace(temp_path, cmd_path)

        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                if res_path.exists():
                    text = res_path.read_text(encoding="ascii", errors="replace")
                    data = _parse_kv(text)
                    data["__raw__"] = text
                    status = data.get("OK", "1").strip().lower()
                    if status not in ("1", "true", "yes"):
                        raise BrokerError(
                            data.get("MESSAGE", f"MT4 bridge rejected {action}")
                        )
                    return data
                time.sleep(self.poll_interval)
            raise BrokerError(
                f"MT4 bridge timeout after {self.timeout:.1f}s for {action}"
            )
        finally:
            cmd_path.unlink(missing_ok=True)
            res_path.unlink(missing_ok=True)
            temp_path.unlink(missing_ok=True)

    # --------------------------------------------------------------- account
    def account_info(self) -> AccountInfo:
        data = self._request("account")
        return AccountInfo(
            balance=_num(data.get("BALANCE")),
            equity=_num(data.get("EQUITY")),
            currency=data.get("CURRENCY", "USD") or "USD",
            leverage=_num(data.get("LEVERAGE"), 1.0),
            margin_free=_num(data.get("MARGINFREE")),
            broker=data.get("BROKER", "MT4"),
        )

    def symbol_info(self, symbol: str) -> SymbolInfo:
        spec = spec_for(symbol, self.config.get("symbols", {}))
        risk = self.config.get("risk", {})
        data = self._request("symbol", symbol=self._broker_symbol(symbol))
        return SymbolInfo(
            symbol=symbol,
            digits=_int(data.get("DIGITS"), spec.digits),
            pip_size=_num(data.get("PIP"), spec.pip_size) or spec.pip_size,
            contract_size=_num(data.get("CONTRACT"), spec.contract_size)
            or spec.contract_size,
            min_lot=_num(data.get("MINLOT"), float(risk.get("min_lot", 0.01)))
            or float(risk.get("min_lot", 0.01)),
            lot_step=_num(data.get("LOTSTEP"), float(risk.get("lot_step", 0.01)))
            or float(risk.get("lot_step", 0.01)),
            max_lot=_num(data.get("MAXLOT"), float(risk.get("max_lot", 50.0)))
            or float(risk.get("max_lot", 50.0)),
            spread=_num(data.get("SPREAD")),
        )

    # ----------------------------------------------------------------- quote
    def quote(self, symbol: str) -> Quote:
        data = self._request("quote", symbol=self._broker_symbol(symbol))
        bid = _num(data.get("BID"))
        ask = _num(data.get("ASK"))
        if bid <= 0 or ask <= 0:
            raise BrokerError(f"MT4 returned no quote for {symbol}")
        return Quote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            time=_parse_time(data.get("TIME")),
        )

    # ----------------------------------------------------------------- orders
    def place_order(self, request: OrderRequest) -> OrderResult:
        try:
            data = self._request(
                "order",
                symbol=self._broker_symbol(request.symbol),
                side=request.side.upper(),
                volume=request.volume,
                sl=request.stop_loss or 0.0,
                tp=request.take_profit or 0.0,
                comment=request.comment,
            )
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))

        ticket = _int(data.get("TICKET"))
        if ticket <= 0:
            return OrderResult(False, message=data.get("MESSAGE", "no ticket returned"))
        return OrderResult(
            True,
            ticket=ticket,
            price=_num(data.get("PRICE")) or None,
            message=data.get("MESSAGE", ""),
            retcode=_int(data.get("RETCODE")),
        )

    def positions(self) -> list[Position]:
        data = self._request("positions")
        positions: list[Position] = []
        for line in data.get("__raw__", "").splitlines():
            if not line.upper().startswith("POSITION="):
                continue
            parts = line.split("=", 1)[1].split("|")
            if len(parts) < 10:
                continue
            positions.append(
                Position(
                    ticket=_int(parts[0]),
                    symbol=parts[1],
                    side=parts[2].lower(),
                    volume=_num(parts[3]),
                    entry=_num(parts[4]),
                    stop_loss=_num(parts[5]) or None,
                    take_profit=_num(parts[6]) or None,
                    profit=_num(parts[7]),
                    comment=parts[8],
                    opened_at=_parse_time(parts[9])
                    or datetime.now(timezone.utc),
                )
            )
        return positions

    def close_position(self, ticket: int) -> OrderResult:
        try:
            data = self._request("close", ticket=ticket)
        except BrokerError as exc:
            return OrderResult(False, message=str(exc))
        return OrderResult(
            True,
            ticket=ticket,
            price=_num(data.get("PRICE")) or None,
            message=f"closed, profit={_num(data.get('PROFIT')):.2f}",
        )
