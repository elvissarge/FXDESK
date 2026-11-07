"""Turn strategies into ranked, risk-sized trade plans."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import pandas as pd

from fxdesk.brokers.base import Quote
from fxdesk.data import DataService
from fxdesk.risk import RiskManager
from fxdesk.strategies.base import Strategy
from fxdesk.strategies.registry import build_strategy
from fxdesk.symbols import spec_for

logger = logging.getLogger(__name__)


@dataclass
class TradePlan:
    symbol: str
    timeframe: str
    strategy: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    volume: float
    risk_amount: float
    reward_amount: float
    risk_reward: float
    confidence: float
    spread_pips: float
    valid: bool
    reason: str
    timestamp: pd.Timestamp
    rationale: str
    rank_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = pd.Timestamp(self.timestamp).isoformat()
        return data


class SignalEngine:
    def __init__(self, config: dict[str, Any], data: DataService | None = None):
        self.config = config
        self.data = data or DataService(config)
        self.risk = RiskManager(config)

    def _quote_for(
        self,
        symbol: str,
        frame: pd.DataFrame,
        quote: Quote | None,
    ) -> Quote:
        if quote is not None:
            return quote

        spec = self.risk.spec(symbol)
        spread_pips = float(
            self.config.get("signals", {}).get(
                "synthetic_spread_pips",
                self.config.get("backtest", {}).get("spread_pips", 1.0),
            )
        )
        mid = float(frame["close"].iloc[-1])
        half = spread_pips / 2.0 * spec.pip_size
        return Quote(symbol=symbol, bid=mid - half, ask=mid + half)

    def plan_from_frame(
        self,
        symbol: str,
        timeframe: str,
        strategy: Strategy,
        frame: pd.DataFrame,
        quote: Quote | None = None,
        equity: float | None = None,
        allow_continuation: bool = True,
    ) -> TradePlan | None:
        if frame is None or frame.empty:
            return None
        if len(frame) < strategy.required_bars():
            return None

        signal = strategy.latest_signal(
            symbol,
            timeframe,
            frame,
            allow_continuation=allow_continuation,
        )
        if signal is None:
            return None

        quote = self._quote_for(symbol, frame, quote)
        spread_pips = float(self.risk.spread_pips(symbol, quote.bid, quote.ask))
        entry = quote.ask if signal.direction == "long" else quote.bid
        signal = signal.with_entry(entry)

        if equity is None:
            equity = float(
                self.config.get("account", {}).get("initial_balance", 10000.0)
            )

        decision = self.risk.position_size(
            symbol,
            equity=equity,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            risk_reward=signal.risk_reward,
            price=signal.entry,
        )

        valid, reason = self.risk.validate_levels(
            signal.direction,
            signal.entry,
            signal.stop_loss,
            signal.take_profit,
            signal.risk_reward,
            spread_pips=spread_pips,
            volume=decision.volume,
        )
        if not decision.valid:
            valid = False
            reason = decision.reason

        plan = TradePlan(
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy.name,
            direction=signal.direction,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            volume=decision.volume,
            risk_amount=decision.risk_amount,
            reward_amount=decision.reward_amount,
            risk_reward=signal.risk_reward,
            confidence=signal.confidence,
            spread_pips=spread_pips,
            valid=valid,
            reason=reason,
            timestamp=signal.timestamp,
            rationale=signal.rationale,
        )
        plan.rank_score = (
            signal.confidence * signal.risk_reward if plan.valid else 0.0
        )
        return plan

    def plan_symbol(
        self,
        symbol: str,
        timeframe: str,
        strategy_name: str,
        quote: Quote | None = None,
        equity: float | None = None,
        allow_continuation: bool = True,
    ) -> TradePlan | None:
        strategy = build_strategy(strategy_name, self.config)
        bars = max(
            int(self.config.get("signals", {}).get("lookback_bars", 500)),
            strategy.required_bars() + 50,
        )
        frame = self.data.fetch_latest(symbol, timeframe, bars=bars, refresh=True)
        return self.plan_from_frame(
            symbol,
            timeframe,
            strategy,
            frame,
            quote=quote,
            equity=equity,
            allow_continuation=allow_continuation,
        )

    def scan(
        self,
        symbols: Iterable[str],
        timeframe: str,
        strategy_names: Iterable[str],
        quotes: dict[str, Quote] | None = None,
        equity: float | None = None,
        allow_continuation: bool = True,
        max_plans: int | None = None,
    ) -> list[TradePlan]:
        names = list(strategy_names)
        strategies = [build_strategy(name, self.config) for name in names]
        if not strategies:
            return []

        lookback = int(self.config.get("signals", {}).get("lookback_bars", 500))
        required = max(strategy.required_bars() for strategy in strategies)
        bars = max(lookback, required + 50)

        plans: list[TradePlan] = []
        for symbol in symbols:
            try:
                frame = self.data.fetch_latest(
                    symbol, timeframe, bars=bars, refresh=True
                )
            except Exception as exc:
                logger.warning("could not fetch %s %s: %s", symbol, timeframe, exc)
                continue

            quote = quotes.get(symbol) if quotes else None
            for strategy in strategies:
                try:
                    plan = self.plan_from_frame(
                        symbol,
                        timeframe,
                        strategy,
                        frame,
                        quote=quote,
                        equity=equity,
                        allow_continuation=allow_continuation,
                    )
                except Exception as exc:
                    logger.warning(
                        "%s %s failed: %s", symbol, strategy.name, exc
                    )
                    continue
                if plan is not None:
                    plans.append(plan)

        plans.sort(key=lambda plan: (plan.valid, plan.rank_score), reverse=True)
        if max_plans is not None:
            plans = plans[: int(max_plans)]
        return plans


def format_plans(plans: list[TradePlan]) -> str:
    if not plans:
        return "No trade plans."

    header = (
        f"{'SYMBOL':<9}{'DIR':<6}{'STRATEGY':<15}{'ENTRY':>11}{'STOP':>11}"
        f"{'TARGET':>11}{'RR':>6}{'LOTS':>8}{'RISK':>10}{'SPREAD':>8}"
        f"{'CONF':>6}  STATUS"
    )
    lines = [header, "-" * len(header)]

    for plan in plans:
        spec = spec_for(plan.symbol)
        digits = spec.digits
        status = "OK" if plan.valid else plan.reason
        lines.append(
            f"{plan.symbol:<9}{plan.direction:<6}{plan.strategy:<15}"
            f"{plan.entry:>11.{digits}f}{plan.stop_loss:>11.{digits}f}"
            f"{plan.take_profit:>11.{digits}f}{plan.risk_reward:>6.2f}"
            f"{plan.volume:>8.2f}{plan.risk_amount:>10.2f}"
            f"{plan.spread_pips:>8.2f}{plan.confidence:>6.2f}  {status}"
        )

    notes = [f"{plan.symbol} {plan.strategy}: {plan.rationale}" for plan in plans]
    return "\n".join(lines) + "\n\nNotes:\n" + "\n".join(f"- {note}" for note in notes)
