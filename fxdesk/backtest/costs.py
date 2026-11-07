"""Session- and volatility-aware transaction cost model.

The default (no ``backtest.cost_model`` block) reproduces the original fixed
spread/slippage behaviour. When a block is present and enabled, spread and
slippage vary by UTC session and, optionally, with ATR-scaled volatility.
"""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd


def parse_session_multipliers(mapping: Mapping[Any, Any] | None) -> list[float]:
    """Expand keys like ``"0-6"`` or ``"22-2"`` into a 24-hour multiplier list."""
    multipliers = [1.0] * 24
    for key, value in (mapping or {}).items():
        text = str(key).strip()
        try:
            if "-" in text:
                left, right = text.split("-", 1)
                start, end = int(left), int(right)
            else:
                start, end = int(text), int(text) + 1
        except ValueError:
            continue

        try:
            factor = float(value)
        except (TypeError, ValueError):
            continue

        for hour in range(24):
            if start <= hour < end or (
                end <= start and (hour >= start or hour < end)
            ):
                multipliers[hour] = factor
    return multipliers


class CostModel:
    """Compute per-bar spread and slippage in pips."""

    def __init__(self, config: dict[str, Any]):
        backtest = config.get("backtest", {})
        self.base_spread = float(backtest.get("spread_pips", 1.0))
        self.base_slippage = float(backtest.get("slippage_pips", 0.2))

        raw = backtest.get("cost_model") or {}
        self.enabled = bool(raw.get("enabled", True)) if raw else False
        self.session_spread = parse_session_multipliers(
            raw.get("session_spread_multipliers")
        )
        self.session_slippage = parse_session_multipliers(
            raw.get("session_slippage_multipliers")
        )
        self.volatility_spread_mult = float(
            raw.get("volatility_spread_mult", 0.0) or 0.0
        )
        self.volatility_slippage_mult = float(
            raw.get("volatility_slippage_mult", 0.0) or 0.0
        )
        self.max_spread = float(raw.get("max_spread_pips", 0.0) or 0.0)
        self.max_slippage = float(raw.get("max_slippage_pips", 0.0) or 0.0)

    @staticmethod
    def _hour(timestamp: Any) -> int:
        return int(pd.Timestamp(timestamp).hour)

    @staticmethod
    def _atr_pips(atr: float, price: float, pip: float) -> float:
        if atr and atr > 0 and pip > 0:
            return float(atr) / float(pip)
        return 0.0

    def spread_pips(
        self,
        timestamp: Any,
        atr: float = 0.0,
        price: float = 0.0,
        pip: float = 0.0001,
    ) -> float:
        if not self.enabled:
            return self.base_spread
        value = self.base_spread * self.session_spread[self._hour(timestamp)]
        if self.volatility_spread_mult:
            value += self.volatility_spread_mult * self._atr_pips(atr, price, pip)
        if self.max_spread > 0:
            value = min(value, self.max_spread)
        return max(value, 0.0)

    def slippage_pips(
        self,
        timestamp: Any,
        atr: float = 0.0,
        price: float = 0.0,
        pip: float = 0.0001,
    ) -> float:
        if not self.enabled:
            return self.base_slippage
        value = self.base_slippage * self.session_slippage[self._hour(timestamp)]
        if self.volatility_slippage_mult:
            value += self.volatility_slippage_mult * self._atr_pips(atr, price, pip)
        if self.max_slippage > 0:
            value = min(value, self.max_slippage)
        return max(value, 0.0)
