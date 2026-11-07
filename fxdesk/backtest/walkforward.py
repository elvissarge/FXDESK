"""Walk-forward parameter selection and out-of-sample evaluation."""

from __future__ import annotations

import copy
import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from fxdesk.backtest.analysis import (
    benchmark_metrics,
    buy_and_hold_equity,
    monte_carlo_trades,
)
from fxdesk.backtest.engine import Backtester
from fxdesk.backtest.metrics import compute_metrics
from fxdesk.errors import ConfigError, DataError
from fxdesk.strategies.registry import build_strategy

DEFAULT_GRIDS: dict[str, dict[str, list[Any]]] = {
    "trend_ma": {
        "fast": [10, 20, 30],
        "slow": [50, 80],
        "trend": [150, 200],
        "atr_mult": [1.5, 2.0, 2.5],
        "rr": [1.5, 2.0],
    },
    "breakout": {
        "lookback": [10, 20, 30],
        "trend": [150, 200],
        "atr_mult": [1.5, 2.0],
        "rr": [1.5, 2.0],
    },
    "mean_reversion": {
        "bb_period": [15, 20],
        "bb_std": [1.5, 2.0],
        "rsi_period": [14],
        "atr_mult": [1.0, 1.5],
        "rr": [1.0, 1.5],
    },
    "composite": {
        "min_score": [0.4, 0.6, 0.8],
        "atr_mult": [1.5, 2.0],
        "rr": [1.5, 2.0],
    },
}


@dataclass
class WalkForwardResult:
    symbol: str
    timeframe: str
    strategy: str
    initial_balance: float
    final_balance: float
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict[str, Any]
    windows: list[dict[str, Any]]
    analysis: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        from fxdesk.backtest.report import format_walkforward_summary

        return format_walkforward_summary(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "strategy": self.strategy,
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "metrics": self.metrics,
            "windows": self.windows,
            "analysis": self.analysis,
        }


class WalkForward:
    """Rolling train/test windows with per-window parameter selection."""

    def __init__(
        self,
        config: dict[str, Any],
        strategy_name: str,
        param_grid: dict[str, list[Any]] | None = None,
        train_bars: int | None = None,
        test_bars: int | None = None,
        step_bars: int | None = None,
        objective: str | None = None,
        min_train_trades: int | None = None,
        max_combinations: int | None = None,
        monte_carlo_iterations: int = 0,
        seed: int = 0,
    ):
        self.config = config
        wf = config.get("walkforward", {}) or {}
        self.strategy_name = strategy_name
        self.train_bars = int(
            train_bars if train_bars is not None else wf.get("train_bars", 1000)
        )
        self.test_bars = int(
            test_bars if test_bars is not None else wf.get("test_bars", 250)
        )
        self.step_bars = int(
            step_bars if step_bars is not None else wf.get("step_bars", self.test_bars)
        )
        self.objective = str(objective or wf.get("objective", "sharpe"))
        self.min_train_trades = int(
            min_train_trades
            if min_train_trades is not None
            else wf.get("min_train_trades", 3)
        )
        self.max_combinations = int(
            max_combinations
            if max_combinations is not None
            else wf.get("max_combinations", 250)
        )
        self.monte_carlo_iterations = int(monte_carlo_iterations)
        self.seed = int(seed)
        self.param_grid = self._resolve_grid(param_grid, wf)

        if self.train_bars < 20 or self.test_bars < 5:
            raise ConfigError("walk-forward train_bars must be >= 20 and test_bars >= 5")
        if self.step_bars < 1:
            self.step_bars = self.test_bars

    def _resolve_grid(
        self,
        param_grid: dict[str, list[Any]] | None,
        wf: dict[str, Any],
    ) -> dict[str, list[Any]]:
        if param_grid:
            return {key: list(values) for key, values in param_grid.items()}
        custom = (wf.get("param_grid") or {}).get(self.strategy_name)
        if custom:
            return {key: list(values) for key, values in custom.items()}
        return {
            key: list(values)
            for key, values in DEFAULT_GRIDS.get(self.strategy_name, {}).items()
        }

    def _combinations(self) -> list[dict[str, Any]]:
        if not self.param_grid:
            return [{}]
        keys = list(self.param_grid)
        combinations: list[dict[str, Any]] = []
        for values in itertools.product(*(self.param_grid[key] for key in keys)):
            combinations.append(dict(zip(keys, values)))
            if len(combinations) >= self.max_combinations:
                break
        return combinations

    def _strategy(self, params: dict[str, Any]):
        cfg = copy.deepcopy(self.config)
        cfg.setdefault("strategies", {}).setdefault(self.strategy_name, {}).update(
            params
        )
        return build_strategy(self.strategy_name, cfg)

    def _backtest_config(self, balance: float) -> dict[str, Any]:
        cfg = copy.deepcopy(self.config)
        backtest = cfg.setdefault("backtest", {})
        backtest["initial_balance"] = float(balance)
        backtest["warmup_bars"] = 0
        return cfg

    def _score(self, metrics: dict[str, Any]) -> float:
        value = metrics.get(self.objective)
        if value is None:
            value = metrics.get("total_return", 0.0)
        try:
            score = float(value)
        except (TypeError, ValueError):
            return 0.0
        return score if math.isfinite(score) else 0.0

    def _run_slice(
        self,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
        strategy_frame: pd.DataFrame,
        start: int,
        end: int,
        balance: float,
    ):
        sub_frame = frame.iloc[start:end]
        sub_signals = strategy_frame.iloc[start:end]
        engine = Backtester(self._backtest_config(balance))
        return engine.run(symbol, timeframe, sub_frame, sub_signals, self.strategy_name)

    def run(
        self,
        symbol: str,
        timeframe: str,
        frame: pd.DataFrame,
    ) -> WalkForwardResult:
        if frame is None or len(frame) < self.train_bars + self.test_bars:
            raise DataError(
                f"walk-forward needs at least {self.train_bars + self.test_bars} bars, "
                f"got {0 if frame is None else len(frame)}"
            )

        frame = frame.sort_index()
        combinations = self._combinations()
        if not combinations:
            raise ConfigError(f"empty parameter grid for {self.strategy_name!r}")

        initial_balance = float(
            self.config.get("backtest", {}).get(
                "initial_balance",
                self.config.get("account", {}).get("initial_balance", 10000.0),
            )
        )
        balance = initial_balance

        equity_parts: list[pd.Series] = []
        trade_parts: list[pd.DataFrame] = []
        windows: list[dict[str, Any]] = []

        start = 0
        while start + self.train_bars + self.test_bars <= len(frame):
            train_start = start
            train_end = start + self.train_bars
            test_start = train_end
            test_end = test_start + self.test_bars

            best_params: dict[str, Any] = {}
            best_key: tuple[float, int] | None = None
            best_metrics: dict[str, Any] = {}

            for params in combinations:
                strategy = self._strategy(params)
                train_signals = strategy.generate_frame(frame.iloc[:train_end])
                result = self._run_slice(
                    symbol,
                    timeframe,
                    frame.iloc[:train_end],
                    train_signals,
                    train_start,
                    train_end,
                    balance,
                )
                trades = int(result.metrics.get("trades", 0) or 0)
                score = self._score(result.metrics)
                qualifies = trades >= self.min_train_trades
                key = (score if qualifies else -math.inf, trades)
                if best_key is None or key > best_key:
                    best_key = key
                    best_params = params
                    best_metrics = result.metrics

            strategy = self._strategy(best_params)
            test_signals = strategy.generate_frame(frame.iloc[:test_end])
            test_result = self._run_slice(
                symbol,
                timeframe,
                frame.iloc[:test_end],
                test_signals,
                test_start,
                test_end,
                balance,
            )

            balance = float(test_result.final_balance)
            if len(test_result.equity):
                equity_parts.append(test_result.equity)
            if len(test_result.trades):
                trades = test_result.trades.copy()
                trades["window"] = len(windows) + 1
                trade_parts.append(trades)

            windows.append(
                {
                    "window": len(windows) + 1,
                    "train_start": str(frame.index[train_start]),
                    "train_end": str(frame.index[train_end - 1]),
                    "test_start": str(frame.index[test_start]),
                    "test_end": str(frame.index[test_end - 1]),
                    "params": dict(best_params),
                    "train_score": self._score(best_metrics),
                    "train_trades": int(best_metrics.get("trades", 0) or 0),
                    "test_return": float(
                        test_result.metrics.get("total_return", 0.0) or 0.0
                    ),
                    "test_trades": int(test_result.metrics.get("trades", 0) or 0),
                    "test_sharpe": float(
                        test_result.metrics.get("sharpe", 0.0) or 0.0
                    ),
                }
            )

            start += self.step_bars

        if not equity_parts:
            raise DataError("walk-forward produced no out-of-sample windows")

        equity = pd.concat(equity_parts)
        equity = equity[~equity.index.duplicated(keep="last")].sort_index()
        equity.name = "equity"

        if trade_parts:
            trades_frame = pd.concat(trade_parts, ignore_index=True)
        else:
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
                    "window",
                ]
            )

        metrics = compute_metrics(equity, trades_frame, timeframe, initial_balance)

        analysis: dict[str, Any] = {}
        oos_frame = frame.loc[equity.index.min() : equity.index.max()]
        benchmark = buy_and_hold_equity(oos_frame, initial_balance)
        if len(benchmark):
            analysis["buy_hold"] = benchmark_metrics(
                benchmark, timeframe, initial_balance
            )
            strategy_return = float(metrics.get("total_return", 0.0) or 0.0)
            buy_hold_return = float(
                analysis["buy_hold"].get("total_return", 0.0) or 0.0
            )
            analysis["comparison"] = {
                "strategy_return": strategy_return,
                "buy_hold_return": buy_hold_return,
                "excess_return": strategy_return - buy_hold_return,
            }
        if self.monte_carlo_iterations and len(trades_frame):
            analysis["monte_carlo"] = monte_carlo_trades(
                trades_frame,
                initial_balance,
                iterations=self.monte_carlo_iterations,
                seed=self.seed,
            )

        return WalkForwardResult(
            symbol=symbol,
            timeframe=timeframe,
            strategy=self.strategy_name,
            initial_balance=initial_balance,
            final_balance=float(equity.iloc[-1]),
            equity=equity,
            trades=trades_frame,
            metrics=metrics,
            windows=windows,
            analysis=analysis,
        )


def save_walkforward_outputs(
    result: WalkForwardResult,
    output_dir: str | Path = "reports",
    plot: bool = False,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{result.symbol}_{result.timeframe}_{result.strategy}_walkforward"

    equity_path = out / f"{stem}_equity.csv"
    result.equity.to_csv(equity_path, index_label="time")

    trades_path = out / f"{stem}_trades.csv"
    result.trades.to_csv(trades_path, index=False)

    windows_path = out / f"{stem}_windows.csv"
    pd.DataFrame(result.windows).to_csv(windows_path, index=False)

    summary_path = out / f"{stem}_summary.json"
    summary_path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )

    paths = {
        "trades": trades_path,
        "equity": equity_path,
        "windows": windows_path,
        "summary": summary_path,
    }

    if plot:
        from fxdesk.backtest.report import plot_equity

        chart_path = out / f"{stem}_equity.png"
        if plot_equity(result, chart_path):
            paths["chart"] = chart_path

    return paths
