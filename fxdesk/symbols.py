"""Symbol metadata and pip/position helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class SymbolSpec:
    symbol: str
    base: str
    quote: str
    digits: int
    pip_size: float
    contract_size: float
    kind: str = "fx"

    @property
    def is_jpy(self) -> bool:
        return self.quote == "JPY"


def _fx(symbol: str, base: str, quote: str) -> SymbolSpec:
    jpy = quote == "JPY"
    return SymbolSpec(
        symbol=symbol,
        base=base,
        quote=quote,
        digits=3 if jpy else 5,
        pip_size=0.01 if jpy else 0.0001,
        contract_size=100000.0,
        kind="fx",
    )


KNOWN: dict[str, SymbolSpec] = {
    # majors
    "EURUSD": _fx("EURUSD", "EUR", "USD"),
    "GBPUSD": _fx("GBPUSD", "GBP", "USD"),
    "USDJPY": _fx("USDJPY", "USD", "JPY"),
    "USDCHF": _fx("USDCHF", "USD", "CHF"),
    "USDCAD": _fx("USDCAD", "USD", "CAD"),
    "AUDUSD": _fx("AUDUSD", "AUD", "USD"),
    "NZDUSD": _fx("NZDUSD", "NZD", "USD"),
    # crosses
    "EURGBP": _fx("EURGBP", "EUR", "GBP"),
    "EURJPY": _fx("EURJPY", "EUR", "JPY"),
    "GBPJPY": _fx("GBPJPY", "GBP", "JPY"),
    "EURCHF": _fx("EURCHF", "EUR", "CHF"),
    "EURAUD": _fx("EURAUD", "EUR", "AUD"),
    "EURCAD": _fx("EURCAD", "EUR", "CAD"),
    "AUDJPY": _fx("AUDJPY", "AUD", "JPY"),
    "CADJPY": _fx("CADJPY", "CAD", "JPY"),
    "CHFJPY": _fx("CHFJPY", "CHF", "JPY"),
    "NZDJPY": _fx("NZDJPY", "NZD", "JPY"),
    "GBPCHF": _fx("GBPCHF", "GBP", "CHF"),
    "GBPAUD": _fx("GBPAUD", "GBP", "AUD"),
    "GBPCAD": _fx("GBPCAD", "GBP", "CAD"),
    "AUDNZD": _fx("AUDNZD", "AUD", "NZD"),
    "AUDCAD": _fx("AUDCAD", "AUD", "CAD"),
    "AUDCHF": _fx("AUDCHF", "AUD", "CHF"),
    "NZDCAD": _fx("NZDCAD", "NZD", "CAD"),
    "NZDCHF": _fx("NZDCHF", "NZD", "CHF"),
    # metals
    "XAUUSD": SymbolSpec("XAUUSD", "XAU", "USD", 2, 0.01, 100.0, "metal"),
    "XAGUSD": SymbolSpec("XAGUSD", "XAG", "USD", 3, 0.001, 5000.0, "metal"),
    # indices / CFD examples (contract sizes differ by broker - override in config)
    "US30": SymbolSpec("US30", "US30", "USD", 1, 1.0, 1.0, "index"),
    "NAS100": SymbolSpec("NAS100", "NAS100", "USD", 1, 1.0, 1.0, "index"),
    "SPX500": SymbolSpec("SPX500", "SPX500", "USD", 1, 0.1, 1.0, "index"),
    "GER40": SymbolSpec("GER40", "GER40", "EUR", 1, 0.1, 1.0, "index"),
    "UK100": SymbolSpec("UK100", "UK100", "GBP", 1, 0.1, 1.0, "index"),
    # energy
    "USOIL": SymbolSpec("USOIL", "USOIL", "USD", 2, 0.01, 1000.0, "commodity"),
    "UKOIL": SymbolSpec("UKOIL", "UKOIL", "USD", 2, 0.01, 1000.0, "commodity"),
    # crypto CFDs
    "BTCUSD": SymbolSpec("BTCUSD", "BTC", "USD", 2, 1.0, 1.0, "crypto"),
    "ETHUSD": SymbolSpec("ETHUSD", "ETH", "USD", 2, 0.1, 1.0, "crypto"),
}


def clean_symbol(symbol: str) -> str:
    """Uppercase and strip separators, keeping broker suffixes."""
    return symbol.strip().upper().replace("/", "").replace("-", "").replace("_", "")


def base_symbol(symbol: str) -> str:
    """Return the canonical instrument code, ignoring broker suffixes."""
    raw = clean_symbol(symbol)
    if raw in KNOWN:
        return raw

    # try a known instrument as a prefix (EURUSD.a, XAUUSDm, US30.cash)
    for code in KNOWN:
        if raw.startswith(code):
            return code

    # generic 6-letter FX pair
    if len(raw) >= 6 and raw[:3].isalpha() and raw[3:6].isalpha():
        return raw[:6]

    return raw


def spec_for(symbol: str, overrides: dict[str, dict[str, Any]] | None = None) -> SymbolSpec:
    key = base_symbol(symbol)
    spec = KNOWN.get(key)

    if spec is None:
        raw = clean_symbol(symbol)
        if len(raw) >= 6 and raw[:3].isalpha() and raw[3:6].isalpha():
            jpy = raw[3:6] == "JPY"
            spec = SymbolSpec(
                symbol=raw,
                base=raw[:3],
                quote=raw[3:6],
                digits=3 if jpy else 5,
                pip_size=0.01 if jpy else 0.0001,
                contract_size=100000.0,
            )
        else:
            raise ValueError(
                f"unknown symbol {symbol!r}; add it to fxdesk/symbols.py or config.symbols"
            )

    if overrides and key in overrides:
        spec = replace(spec, **overrides[key])

    return replace(spec, symbol=symbol)


def pip_value_per_lot(
    spec: SymbolSpec,
    price: float,
    account_currency: str = "USD",
    quote_to_account: float | None = None,
) -> float:
    """Approximate value of one pip for one lot, in account currency."""
    base_value = spec.contract_size * spec.pip_size

    if spec.quote.upper() == account_currency.upper():
        return base_value

    if spec.base.upper() == account_currency.upper() and price > 0:
        return base_value / price

    # cross pair: convert quote currency value into the account currency
    rate = quote_to_account if quote_to_account is not None else 1.0
    return base_value * rate


def price_to_pips(spec: SymbolSpec, distance: float) -> float:
    if spec.pip_size <= 0:
        return 0.0
    return abs(distance) / spec.pip_size


def pips_to_price(spec: SymbolSpec, pips: float) -> float:
    return pips * spec.pip_size


def known_symbols() -> list[str]:
    return sorted(KNOWN)
