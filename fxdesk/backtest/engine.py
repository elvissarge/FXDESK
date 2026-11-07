"""Event-driven single-symbol backtester with spread, slippage and SL/TP."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from fxdesk.backtest.costs import CostModel
from fxdesk.backtest.metrics import compute_metrics
from fxdesk.errors import DataError
from fxdesk.risk import RiskManager
from fxdesk.symbols import pip_value_per_lot, spec_for


@dataclass
class Trade:
    ticket: int
    symbol: str
    side: str
    volume: float
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    stop_loss: float
    take_profit: float
    profit: float
    pips: float
    reason: str
    strategy: str
    risk_amount: float
    risk_reward: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entry_time"] = pd.Timestamp(self.entry_time).isoformat()
        data["exit_time"] = pd.Timestamp(self.exit_time).isoformat()
        return data


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    strategy: str
    initial_balance: float
    final_balance: float
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict[str, Any]
    analysis: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        from fxdesk.backtest.report import format_summary

        return format_summary(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "metrics": self.metrics,
            "analysis": self.analysis,
        }


class Backtester:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.bt = config.get("backtest", {})
        self.risk = RiskManager(config)
        self.currency = str(config.get("account", {}).get("currency", "USD"))
        self.symbol_overrides = config.get("symbols", {})
        self.pip_value_rates = {
            str(key).upper(): float(value)
            for key, value in config.get("pip_value_rates", {}).items()
        }

    def run(
        self,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
        strategy_frame: pd.DataFrame,
        strategy_name: str = "",
    ) -> BacktestResult:
        if frame is None or len(frame) < 2:
            raise DataError("not enough bars to backtest")

        frame = frame.sort_index()
        strategy_frame = strategy_frame.reindex(frame.index)

        signals = (
            strategy_frame.get("signal", pd.Series(0, index=frame.index))
            .fillna(0)
            .astype(int)
            .to_numpy()
        )
        stop_distances = (
            strategy_frame.get("stop_distance", pd.Series(np.nan, index=frame.index))
            .to_numpy(dtype="float64")
        )
        reward_ratios = (
            strategy_frame.get("rr", pd.Series(2.0, index=frame.index))
            .fillna(2.0)
            .to_numpy(dtype="float64")
        )

        spec = spec_for(symbol, self.symbol_overrides)
        pip = spec.pip_size

        initial_balance = float(
            self.bt.get(
                "initial_balance",
                self.config.get("account", {}).get("initial_balance", 10000.0),
            )
        )
        cost = CostModel(self.config)
        commission_per_lot = float(self.bt.get("commission_per_lot", 0.0))
        swap_pips_per_day = float(self.bt.get("swap_pips_per_day", 0.0))
        allow_short = bool(self.bt.get("allow_short", True))
        warmup = int(self.bt.get("warmup_bars", 0))
        close_at_end = bool(self.bt.get("close_at_end", True))

        atr_series = strategy_frame.get("atr")
        if atr_series is None:
            atr_array = np.zeros(len(frame), dtype="float64")
        else:
            atr_array = (
                pd.to_numeric(atr_series, errors="coerce")
                .fillna(0.0)
                .to_numpy(dtype="float64")
            )

        balance = initial_balance
        position: dict[str, Any] | None = None
        pending: dict[str, Any] | None = None
        trades: list[Trade] = []

        equity_times: list[datetime] = []
        equity_values: list[float] = []

        bars = list(frame.itertuples(index=True, name="Bar"))

        for index, bar in enumerate(bars):
            timestamp = bar.Index
            open_price = float(bar.open)
            high = float(bar.high)
            low = float(bar.low)
            close = float(bar.close)

            bar_atr = float(atr_array[index])
            bar_spread_pips = cost.spread_pips(timestamp, bar_atr, close, pip)
            bar_half_spread = bar_spread_pips / 2.0 * pip
            bar_slippage = (
                cost.slippage_pips(timestamp, bar_atr, close, pip) * pip
            )

            if pending is not None and position is None:
                position = self._build_position(
                    pending,
                    open_price,
                    timestamp,
                    balance,
                    symbol,
                    spec,
                    bar_half_spread,
                    bar_slippage,
                    bar_spread_pips,
                )
                pending = None

            if position is not None:
                exit_info = self._check_exit(
                    position, open_price, high, low, spec, bar_slippage
                )
                if exit_info is not None:
                    exit_price, reason = exit_info
                    trade, net = self._close_position(
                        position,
                        exit_price,
                        timestamp,
                        reason,
                        symbol,
                        spec,
                        commission_per_lot,
                        swap_pips_per_day,
                        ticket=len(trades) + 1,
                    )
                    trade.strategy = strategy_name
                    balance += net
                    trades.append(trade)
                    position = None

            unrealized = 0.0
            if position is not None:
                unrealized = self._unrealized(position, close, spec)

            equity_times.append(timestamp)
            equity_values.append(balance + unrealized)

            if (
                position is None
                and pending is None
                and index + 1 < len(bars)
                and index >= warmup
            ):
                direction = int(signals[index])
                stop_distance = float(stop_distances[index])
                reward_ratio = float(reward_ratios[index])

                if direction != 0 and (allow_short or direction > 0):
                    if (
                        np.isfinite(stop_distance)
                        and stop_distance > 0
                        and np.isfinite(reward_ratio)
                        and reward_ratio > 0
                    ):
                        pending = {
                            "direction": direction,
                            "stop_distance": stop_distance,
                            "reward_ratio": reward_ratio,
                            "signal_time": timestamp,
                            "signal_index": index,
                        }

        if position is not None and close_at_end:
            last = bars[-1]
            exit_price = float(last.close)
            exit_half = float(position.get("half_spread", 0.0))
            exit_slip = float(position.get("slippage", 0.0))
            if position["side"] == "long":
                exit_price = exit_price - exit_half - exit_slip
            else:
                exit_price = exit_price + exit_half + exit_slip

            trade, net = self._close_position(
                position,
                exit_price,
                last.Index,
                "end_of_data",
                symbol,
                spec,
                commission_per_lot,
                swap_pips_per_day,
                ticket=len(trades) + 1,
            )
            trade.strategy = strategy_name
            balance += net
            trades.append(trade)
            position = None
            if equity_values:
                equity_values[-1] = balance

        equity = pd.Series(
            equity_values,
            index=pd.DatetimeIndex(equity_times, name="time"),
            name="equity",
            dtype="float64",
        )

        trade_dicts = [trade.to_dict() for trade in trades]
        trades_frame = pd.DataFrame(trade_dicts)
        if trades_frame.empty:
            trades_frame = pd.DataFrame(
                columns=[
                    "ticket",
                    "symbol",
                    "side",
                    "volume",
                    "entry_time",
                    "entry_price",
                    "exit_time",
                    "exit_price",
                    "stop_loss",
                    "take_profit",
                    "profit",
                    "pips",
                    "reason",
                    "strategy",
                    "risk_amount",
                    "risk_reward",
                ]
            )

        metrics = compute_metrics(equity, trades_frame, timeframe, initial_balance)

        return BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            strategy=strategy_name,
            initial_balance=initial_balance,
            final_balance=float(equity.iloc[-1]) if len(equity) else initial_balance,
            equity=equity,
            trades=trades_frame,
            metrics=metrics,
        )

    def _build_position(
        self,
        pending: dict[str, Any],
        open_price: float,
        timestamp: datetime,
        balance: float,
        symbol: str,
        spec,
        half_spread: float,
        slippage: float,
        spread_pips: float,
    ) -> dict[str, Any] | None:
        direction = int(pending["direction"])
        stop_distance = float(pending["stop_distance"])
        reward_ratio = float(pending["reward_ratio"])

        if direction > 0:
            side = "long"
            entry = open_price + half_spread + slippage
            stop_loss = entry - stop_distance
            take_profit = entry + stop_distance * reward_ratio
        else:
            side = "short"
            entry = open_price - half_spread - slippage
            stop_loss = entry + stop_distance
            take_profit = entry - stop_distance * reward_ratio

        decision = self.risk.position_size(
            symbol,
            equity=balance,
            entry=entry,
            stop_loss=stop_loss,
            risk_reward=reward_ratio,
            price=entry,
        )
        if not decision.valid:
            return None

        valid, _reason = self.risk.validate_levels(
            side,
            entry,
            stop_loss,
            take_profit,
            reward_ratio,
            spread_pips=spread_pips,
            volume=decision.volume,
        )
        if not valid:
            return None

        return {
            "side": side,
            "entry_time": timestamp,
            "entry_price": entry,
            "volume": decision.volume,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_amount": decision.risk_amount,
            "risk_reward": reward_ratio,
            "entry_index": int(pending["signal_index"]) + 1,
            "half_spread": half_spread,
            "slippage": slippage,
        }

    def _check_exit(
        self,
        position: dict[str, Any],
        open_price: float,
        high: float,
        low: float,
        spec,
        slippage: float = 0.0,
    ) -> tuple[float, str] | None:
        side = position["side"]
        stop_loss = float(position["stop_loss"])
        take_profit = float(position["take_profit"])

        if side == "long":
            if low <= stop_loss:
                price = min(open_price, stop_loss) - slippage
                return price, "stop_loss"
            if high >= take_profit:
                price = max(open_price, take_profit)
                return price, "take_profit"
        else:
            if high >= stop_loss:
                price = max(open_price, stop_loss) + slippage
                return price, "stop_loss"
            if low <= take_profit:
                price = min(open_price, take_profit)
                return price, "take_profit"

        return None

    def _close_position(
        self,
        position: dict[str, Any],
        exit_price: float,
        exit_time: datetime,
        reason: str,
        symbol: str,
        spec,
        commission_per_lot: float,
        swap_pips_per_day: float,
        ticket: int,
    ) -> tuple[Trade, float]:
        side = position["side"]
        entry = float(position["entry_price"])
        volume = float(position["volume"])

        diff = exit_price - entry if side == "long" else entry - exit_price
        pip_value = self._pip_value(spec, exit_price)
        gross = (diff / spec.pip_size) * pip_value * volume if spec.pip_size > 0 else 0.0
        commission = commission_per_lot * volume

        held_days = max(
            (pd.Timestamp(exit_time) - pd.Timestamp(position["entry_time"])).total_seconds()
            / 86400.0,
            0.0,
        )
        swap = swap_pips_per_day * pip_value * volume * held_days
        net = gross - commission - swap

        trade = Trade(
            ticket=ticket,
            symbol=symbol,
            side=side,
            volume=volume,
            entry_time=position["entry_time"],
            entry_price=entry,
            exit_time=exit_time,
            exit_price=exit_price,
            stop_loss=float(position["stop_loss"]),
            take_profit=float(position["take_profit"]),
            profit=net,
            pips=diff / spec.pip_size if spec.pip_size > 0 else 0.0,
            reason=reason,
            strategy="",
            risk_amount=float(position["risk_amount"]),
            risk_reward=float(position["risk_reward"]),
        )
        return trade, net

    def _unrealized(self, position: dict[str, Any], price: float, spec) -> float:
        side = position["side"]
        entry = float(position["entry_price"])
        volume = float(position["volume"])
        diff = price - entry if side == "long" else entry - price
        pip_value = self._pip_value(spec, price)
        return (diff / spec.pip_size) * pip_value * volume if spec.pip_size > 0 else 0.0

    def _pip_value(self, spec, price: float) -> float:
        rate = self.pip_value_rates.get(spec.quote.upper(), 1.0)
        return pip_value_per_lot(spec, price, self.currency, rate)
