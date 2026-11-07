"""Paper-trading loop: live quotes, signals, simulated orders, persistence."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from fxdesk.brokers.base import OrderRequest, Quote
from fxdesk.brokers.paper import PaperBroker
from fxdesk.data import DataService
from fxdesk.live.feed import QuoteFeed, build_feed
from fxdesk.risk import RiskManager
from fxdesk.signals.engine import SignalEngine, TradePlan
from fxdesk.strategies.registry import build_strategy

logger = logging.getLogger(__name__)


class PaperRunner:
    def __init__(
        self,
        config: dict[str, Any],
        broker: PaperBroker | None = None,
        feed: QuoteFeed | None = None,
        data: DataService | None = None,
        state_file: str | Path | None = None,
    ):
        self.config = config
        self.data = data or DataService(config)
        self.broker = broker or PaperBroker(config)
        self.feed = feed or build_feed(config, data=self.data)
        self.risk = RiskManager(config)
        self.signals = SignalEngine(config, data=self.data)

        self.state_file = Path(
            state_file or config.get("paper", {}).get("state_file", "paper_state.json")
        )
        if self.broker.load_state(self.state_file):
            logger.info("restored paper state from %s", self.state_file)

        self._day = datetime.now(timezone.utc).date()
        self._day_start_balance = self.broker.balance

    def run(
        self,
        symbols: Iterable[str],
        timeframe: str,
        strategies: Iterable[str],
        poll_seconds: float | None = None,
        once: bool = False,
        allow_continuation: bool = False,
    ) -> None:
        symbol_list = list(symbols)
        strategy_list = list(strategies)
        interval = float(
            poll_seconds
            if poll_seconds is not None
            else self.config.get("paper", {}).get("poll_seconds", 15)
        )

        logger.info(
            "paper trading %s on %s with %s (every %.0fs)",
            symbol_list,
            timeframe,
            strategy_list,
            interval,
        )

        try:
            while True:
                self.cycle(
                    symbol_list,
                    timeframe,
                    strategy_list,
                    allow_continuation=allow_continuation,
                )
                if once:
                    break
                time.sleep(max(interval, 1.0))
        except KeyboardInterrupt:
            logger.info("paper trading stopped by user")
        finally:
            self.broker.save_state(self.state_file)
            self.feed.close()
            logger.info("paper state saved to %s", self.state_file)

    def cycle(
        self,
        symbols: list[str],
        timeframe: str,
        strategies: list[str],
        allow_continuation: bool = False,
    ) -> list[TradePlan]:
        self._roll_day()

        quotes: dict[str, Quote] = {}
        for symbol in symbols:
            try:
                quote = self.feed.get_quote(symbol)
            except Exception as exc:
                logger.warning("quote failed for %s: %s", symbol, exc)
                continue

            quotes[symbol] = quote
            for trade in self.broker.process_quote(quote):
                logger.info(
                    "closed #%s %s %s %.2f lots at %.5f -> %.2f (%s)",
                    trade.ticket,
                    trade.symbol,
                    trade.side,
                    trade.volume,
                    trade.exit,
                    trade.profit,
                    trade.reason,
                )

        if self._daily_loss_breached():
            logger.warning(
                "daily loss limit hit (start %.2f, equity %.2f); no new entries",
                self._day_start_balance,
                self.broker.account_info().equity,
            )
            self.broker.save_state(self.state_file)
            return []

        opened: list[TradePlan] = []
        open_symbols = {position.symbol for position in self.broker.positions()}
        strategy_objects = [build_strategy(name, self.config) for name in strategies]
        if not strategy_objects:
            self.broker.save_state(self.state_file)
            return []

        lookback = int(self.config.get("signals", {}).get("lookback_bars", 500))
        required = max(strategy.required_bars() for strategy in strategy_objects)
        bars = max(lookback, required + 50)

        for symbol in symbols:
            if not self.risk.can_open_more(len(self.broker.positions())):
                break
            if symbol in open_symbols:
                continue
            if symbol not in quotes:
                continue

            try:
                frame = self.feed.get_bars(symbol, timeframe, bars)
            except Exception as exc:
                logger.warning("bars failed for %s: %s", symbol, exc)
                continue

            equity = self.broker.account_info().equity

            for strategy in strategy_objects:
                try:
                    plan = self.signals.plan_from_frame(
                        symbol,
                        timeframe,
                        strategy,
                        frame,
                        quote=quotes[symbol],
                        equity=equity,
                        allow_continuation=allow_continuation,
                    )
                except Exception as exc:
                    logger.warning(
                        "signal failed for %s %s: %s", symbol, strategy.name, exc
                    )
                    continue

                if plan is None:
                    continue
                if not plan.valid:
                    logger.info(
                        "skipping %s %s: %s", symbol, strategy.name, plan.reason
                    )
                    continue

                side = "buy" if plan.direction == "long" else "sell"
                result = self.broker.place_order(
                    OrderRequest(
                        symbol=symbol,
                        side=side,
                        volume=plan.volume,
                        stop_loss=plan.stop_loss,
                        take_profit=plan.take_profit,
                        comment=plan.strategy,
                    )
                )

                if result.ok:
                    logger.info(
                        "opened #%s %s %s %.2f lots @ %.5f SL %.5f TP %.5f (%s)",
                        result.ticket,
                        symbol,
                        side,
                        plan.volume,
                        result.price,
                        plan.stop_loss,
                        plan.take_profit,
                        plan.strategy,
                    )
                    opened.append(plan)
                    open_symbols.add(symbol)
                    break
                else:
                    logger.warning("order rejected for %s: %s", symbol, result.message)

        self.broker.save_state(self.state_file)
        return opened

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._day_start_balance = self.broker.balance

    def _daily_loss_breached(self) -> bool:
        limit_pct = float(self.config.get("risk", {}).get("max_daily_loss_pct", 3.0))
        if limit_pct <= 0 or self._day_start_balance <= 0:
            return False
        equity = self.broker.account_info().equity
        loss_pct = (self._day_start_balance - equity) / self._day_start_balance * 100.0
        return loss_pct >= limit_pct
