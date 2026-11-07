"""Performance metrics for a backtest."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from fxdesk.timeframes import periods_per_year


def _finite(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame,
    timeframe: str,
    initial_balance: float,
) -> dict:
    metrics: dict = {
        "initial_balance": float(initial_balance),
        "final_balance": float(equity.iloc[-1]) if len(equity) else float(initial_balance),
        "total_return": 0.0,
        "cagr": 0.0,
        "annual_volatility": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_drawdown": 0.0,
        "max_drawdown_abs": 0.0,
        "calmar": 0.0,
        "trades": 0,
        "win_rate": 0.0,
        "profit_factor": None,
        "expectancy": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "payoff_ratio": None,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "total_pips": 0.0,
        "long_trades": 0,
        "short_trades": 0,
        "bars": int(len(equity)),
    }

    if equity is None or len(equity) == 0:
        return metrics

    equity = equity.astype(float)
    final_balance = float(equity.iloc[-1])
    metrics["final_balance"] = final_balance
    metrics["total_return"] = final_balance / initial_balance - 1.0

    periods = periods_per_year(timeframe)
    bars = len(equity)
    years = bars / periods if periods > 0 else 0.0

    if years > 0 and initial_balance > 0 and final_balance > 0:
        metrics["cagr"] = (final_balance / initial_balance) ** (1.0 / years) - 1.0

    returns = equity.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) > 1:
        mean_return = returns.mean()
        std_return = returns.std(ddof=0)
        metrics["annual_volatility"] = float(std_return * math.sqrt(periods))

        if std_return > 0:
            metrics["sharpe"] = float(mean_return * periods / (std_return * math.sqrt(periods)))

        downside = returns[returns < 0]
        downside_std = downside.std(ddof=0)
        if downside_std > 0:
            metrics["sortino"] = float(
                mean_return * periods / (downside_std * math.sqrt(periods))
            )

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    if len(drawdown):
        metrics["max_drawdown"] = float(drawdown.min())
        peak = running_max.loc[drawdown.idxmin()] if not drawdown.empty else running_max.iloc[0]
        trough = equity.loc[drawdown.idxmin()]
        metrics["max_drawdown_abs"] = float(trough - peak)

    if metrics["max_drawdown"] < 0 and metrics["cagr"]:
        metrics["calmar"] = float(metrics["cagr"] / abs(metrics["max_drawdown"]))

    if trades is None or len(trades) == 0:
        return metrics

    profits = pd.to_numeric(trades["profit"], errors="coerce").dropna()
    metrics["trades"] = int(len(profits))
    if len(profits) == 0:
        return metrics

    wins = profits[profits > 0]
    losses = profits[profits < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())

    metrics["win_rate"] = float(len(wins) / len(profits))
    metrics["gross_profit"] = gross_profit
    metrics["gross_loss"] = gross_loss
    metrics["expectancy"] = float(profits.mean())
    metrics["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    metrics["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    metrics["profit_factor"] = _finite(
        gross_profit / abs(gross_loss) if gross_loss != 0 else None
    )
    metrics["payoff_ratio"] = _finite(
        metrics["avg_win"] / abs(metrics["avg_loss"]) if metrics["avg_loss"] else None
    )

    if "pips" in trades.columns:
        metrics["total_pips"] = float(
            pd.to_numeric(trades["pips"], errors="coerce").fillna(0.0).sum()
        )
    if "side" in trades.columns:
        metrics["long_trades"] = int((trades["side"] == "long").sum())
        metrics["short_trades"] = int((trades["side"] == "short").sum())

    return metrics
