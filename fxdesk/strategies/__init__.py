"""Strategy package."""

from fxdesk.strategies.base import Signal, Strategy
from fxdesk.strategies.registry import build_strategy, strategy_names

__all__ = ["Signal", "Strategy", "build_strategy", "strategy_names"]
