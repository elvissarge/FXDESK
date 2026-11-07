"""Timeframe parsing and annualisation helpers."""

from __future__ import annotations

from fxdesk.errors import ConfigError

_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "8h": 480,
    "1d": 1440,
    "1w": 10080,
}

_ALIASES: dict[str, str] = {
    "m1": "1m",
    "m5": "5m",
    "m15": "15m",
    "m30": "30m",
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "1h": "1h",
    "h1": "1h",
    "60m": "1h",
    "2h": "2h",
    "h2": "2h",
    "120m": "2h",
    "4h": "4h",
    "h4": "4h",
    "240m": "4h",
    "8h": "8h",
    "h8": "8h",
    "1d": "1d",
    "d1": "1d",
    "1day": "1d",
    "daily": "1d",
    "1w": "1w",
    "w1": "1w",
    "1week": "1w",
    "weekly": "1w",
}

_PANDAS_RULE: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "8h": "8h",
    "1d": "1D",
    "1w": "1W",
}

# 24x5 FX market approximation
_PERIODS_PER_YEAR: dict[str, float] = {
    "1m": 60 * 24 * 252,
    "5m": 12 * 24 * 252,
    "15m": 4 * 24 * 252,
    "30m": 2 * 24 * 252,
    "1h": 24 * 252,
    "2h": 12 * 252,
    "4h": 6 * 252,
    "8h": 3 * 252,
    "1d": 252,
    "1w": 52,
}


def normalize_timeframe(timeframe: str) -> str:
    key = timeframe.strip().lower()
    if key in _MINUTES:
        return key
    if key in _ALIASES:
        return _ALIASES[key]
    raise ConfigError(
        f"unsupported timeframe {timeframe!r}; use one of {', '.join(_MINUTES)}"
    )


def timeframe_minutes(timeframe: str) -> int:
    return _MINUTES[normalize_timeframe(timeframe)]


def pandas_rule(timeframe: str) -> str:
    return _PANDAS_RULE[normalize_timeframe(timeframe)]


def periods_per_year(timeframe: str) -> float:
    return _PERIODS_PER_YEAR[normalize_timeframe(timeframe)]


def is_intraday(timeframe: str) -> bool:
    return timeframe_minutes(timeframe) < 1440


def supported_timeframes() -> list[str]:
    return list(_MINUTES)
