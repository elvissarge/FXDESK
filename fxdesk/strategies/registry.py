"""Strategy registry."""

from __future__ import annotations

from typing import Any

from fxdesk.errors import ConfigError
from fxdesk.strategies.base import Strategy
from fxdesk.strategies.breakout import BreakoutStrategy
from fxdesk.strategies.composite import CompositeStrategy
from fxdesk.strategies.mean_reversion import MeanReversionStrategy
from fxdesk.strategies.trend_ma import TrendMAStrategy

_REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls
    for cls in (
        TrendMAStrategy,
        BreakoutStrategy,
        MeanReversionStrategy,
        CompositeStrategy,
    )
}


def build_strategy(name: str, config: dict[str, Any]) -> Strategy:
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ConfigError(f"unknown strategy {name!r}; choose from {sorted(_REGISTRY)}")
    params = (config.get("strategies") or {}).get(name, {})
    return cls(params=params, config=config)


def strategy_names() -> list[str]:
    return sorted(_REGISTRY)
