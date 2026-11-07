"""Position sizing and trade validation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from fxdesk.symbols import SymbolSpec, pip_value_per_lot, spec_for


@dataclass
class RiskDecision:
    volume: float
    risk_amount: float
    reward_amount: float
    valid: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RiskManager:
    def __init__(self, config: dict[str, Any]):
        risk = config.get("risk", {})
        self.risk_per_trade = float(risk.get("risk_per_trade", 0.01))
        self.min_lot = float(risk.get("min_lot", 0.01))
        self.lot_step = float(risk.get("lot_step", 0.01))
        self.max_lot = float(risk.get("max_lot", 50.0))
        self.min_risk_reward = float(risk.get("min_risk_reward", 1.5))
        self.max_spread_pips = float(risk.get("max_spread_pips", 2.0))
        self.max_open_positions = int(risk.get("max_open_positions", 3))
        self.account_currency = str(config.get("account", {}).get("currency", "USD"))
        self.symbol_overrides = config.get("symbols", {})
        self.pip_value_rates = {
            str(key).upper(): float(value)
            for key, value in config.get("pip_value_rates", {}).items()
        }

    def spec(self, symbol: str) -> SymbolSpec:
        return spec_for(symbol, self.symbol_overrides)

    def spread_pips(self, symbol: str, bid: float, ask: float) -> float:
        spec = self.spec(symbol)
        if spec.pip_size <= 0:
            return 0.0
        return float(max(ask - bid, 0.0) / spec.pip_size)

    def pip_value(
        self,
        symbol: str,
        price: float,
        quote_to_account: float | None = None,
    ) -> float:
        spec = self.spec(symbol)
        if quote_to_account is None:
            quote_to_account = self.pip_value_rates.get(spec.quote.upper(), 1.0)
        return pip_value_per_lot(spec, price, self.account_currency, quote_to_account)

    def position_size(
        self,
        symbol: str,
        equity: float,
        entry: float,
        stop_loss: float,
        risk_reward: float,
        price: float | None = None,
        quote_to_account: float | None = None,
    ) -> RiskDecision:
        spec = self.spec(symbol)
        stop_distance = abs(entry - stop_loss)
        stop_pips = stop_distance / spec.pip_size if spec.pip_size > 0 else 0.0

        if stop_pips <= 0:
            return RiskDecision(0.0, 0.0, 0.0, False, "stop distance is zero")
        if equity <= 0:
            return RiskDecision(0.0, 0.0, 0.0, False, "equity is zero or negative")

        reference_price = price if price is not None else entry
        pip_value = self.pip_value(symbol, reference_price, quote_to_account)
        if pip_value <= 0:
            return RiskDecision(0.0, 0.0, 0.0, False, "pip value is zero")

        risk_amount = equity * self.risk_per_trade
        raw_lots = risk_amount / (stop_pips * pip_value)

        steps = math.floor(raw_lots / self.lot_step + 1e-9)
        lots = min(steps * self.lot_step, self.max_lot)
        lots = round(lots, 8)

        if lots < self.min_lot:
            return RiskDecision(
                0.0,
                risk_amount,
                0.0,
                False,
                f"calculated size {raw_lots:.4f} is below min lot {self.min_lot}",
            )

        actual_risk = stop_pips * pip_value * lots
        reward = actual_risk * max(risk_reward, 0.0)
        return RiskDecision(
            volume=lots,
            risk_amount=actual_risk,
            reward_amount=reward,
            valid=True,
        )

    def validate_levels(
        self,
        direction: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        risk_reward: float,
        spread_pips: float = 0.0,
        volume: float = 1.0,
    ) -> tuple[bool, str]:
        if volume <= 0:
            return False, "volume is zero"
        if direction == "long":
            if not (stop_loss < entry < take_profit):
                return False, "long levels must satisfy stop < entry < target"
        elif direction == "short":
            if not (stop_loss > entry > take_profit):
                return False, "short levels must satisfy stop > entry > target"
        else:
            return False, f"unknown direction {direction!r}"

        if risk_reward + 1e-9 < self.min_risk_reward:
            return False, (
                f"reward/risk {risk_reward:.2f} is below minimum "
                f"{self.min_risk_reward:.2f}"
            )
        if spread_pips > self.max_spread_pips + 1e-9:
            return False, (
                f"spread {spread_pips:.2f} pips exceeds maximum "
                f"{self.max_spread_pips:.2f}"
            )
        return True, "ok"

    def can_open_more(self, open_positions: int) -> bool:
        return open_positions < self.max_open_positions
