"""Post-backtest analysis: buy-and-hold benchmark and Monte Carlo resampling."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from fxdesk.backtest.metrics import compute_metrics


def buy_and_hold_equity(
    frame: pd.DataFrame, initial_balance: float
) -> pd.Series:
    """Equity curve for simply buying at the first close and holding."""
    if frame is None or frame.empty or "close" not in frame:
        return pd.Series(dtype="float64")
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty or float(close.iloc[0]) <= 0:
        return pd.Series(dtype="float64")
    return (initial_balance * close / float(close.iloc[0])).rename("equity")


def benchmark_metrics(
    equity: pd.Series, timeframe: str, initial_balance: float
) -> dict[str, Any]:
    return compute_metrics(equity, pd.DataFrame(), timeframe, initial_balance)


def monte_carlo_trades(
    trades: pd.DataFrame,
    initial_balance: float,
    iterations: int = 1000,
    seed: int = 0,
) -> dict[str, Any]:
    """Bootstrap trade order to estimate the distribution of outcomes."""
    empty = {
        "iterations": 0,
        "trades_per_run": 0,
        "prob_profit": 0.0,
        "median_return": 0.0,
        "p05_return": 0.0,
        "p95_return": 0.0,
        "median_final": float(initial_balance),
        "p05_final": float(initial_balance),
        "p95_final": float(initial_balance),
        "median_max_drawdown": 0.0,
        "p05_max_drawdown": 0.0,
        "median_worst_streak": 0.0,
    }
    if trades is None or len(trades) == 0 or "profit" not in trades:
        return empty

    profits = (
        pd.to_numeric(trades["profit"], errors="coerce")
        .dropna()
        .to_numpy(dtype="float64")
    )
    if len(profits) == 0:
        return empty

    iterations = max(int(iterations), 1)
    rng = np.random.default_rng(seed)
    count = len(profits)
    finals = np.empty(iterations, dtype="float64")
    drawdowns = np.empty(iterations, dtype="float64")
    streaks = np.empty(iterations, dtype="float64")

    for i in range(iterations):
        sample = rng.choice(profits, size=count, replace=True)
        curve = initial_balance + np.cumsum(sample)
        peaks = np.maximum.accumulate(curve)
        drawdowns[i] = float((curve / peaks - 1.0).min())
        finals[i] = float(curve[-1])

        worst = current = 0
        for profit in sample:
            if profit < 0:
                current += 1
                worst = max(worst, current)
            else:
                current = 0
        streaks[i] = float(worst)

    returns = finals / float(initial_balance) - 1.0

    def percentile(values: np.ndarray, q: float) -> float:
        return float(np.percentile(values, q))

    return {
        "iterations": iterations,
        "trades_per_run": count,
        "prob_profit": float((returns > 0).mean()),
        "median_return": float(np.median(returns)),
        "p05_return": percentile(returns, 5),
        "p95_return": percentile(returns, 95),
        "median_final": float(np.median(finals)),
        "p05_final": percentile(finals, 5),
        "p95_final": percentile(finals, 95),
        "median_max_drawdown": float(np.median(drawdowns)),
        "p05_max_drawdown": percentile(drawdowns, 5),
        "median_worst_streak": float(np.median(streaks)),
    }


def analyze_result(
    result: Any,
    frame: pd.DataFrame,
    monte_carlo_iterations: int = 0,
    seed: int = 0,
) -> dict[str, Any]:
    """Build the analysis block attached to a backtest result."""
    analysis: dict[str, Any] = {}

    benchmark = buy_and_hold_equity(frame, result.initial_balance)
    if len(benchmark):
        analysis["buy_hold"] = benchmark_metrics(
            benchmark, result.timeframe, result.initial_balance
        )
        strategy_return = float(result.metrics.get("total_return", 0.0) or 0.0)
        buy_hold_return = float(
            analysis["buy_hold"].get("total_return", 0.0) or 0.0
        )
        analysis["comparison"] = {
            "strategy_return": strategy_return,
            "buy_hold_return": buy_hold_return,
            "excess_return": strategy_return - buy_hold_return,
        }

    if monte_carlo_iterations and len(result.trades):
        analysis["monte_carlo"] = monte_carlo_trades(
            result.trades,
            result.initial_balance,
            iterations=monte_carlo_iterations,
            seed=seed,
        )

    return analysis
