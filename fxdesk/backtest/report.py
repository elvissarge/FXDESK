"""Backtest reporting helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fxdesk.backtest.engine import BacktestResult


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}%"


def _num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):,.{digits}f}"


def _analysis_lines(analysis: dict[str, Any] | None) -> list[str]:
    if not analysis:
        return []

    lines: list[str] = []
    comparison = analysis.get("comparison")
    if comparison:
        lines.extend(
            [
                "-" * 64,
                f"Strategy return     {_pct(comparison.get('strategy_return'))}",
                f"Buy & hold return   {_pct(comparison.get('buy_hold_return'))}",
                f"Excess vs B&H       {_pct(comparison.get('excess_return'))}",
            ]
        )

    monte = analysis.get("monte_carlo")
    if monte and monte.get("iterations"):
        lines.extend(
            [
                "-" * 64,
                f"Monte Carlo         {monte['iterations']} runs, "
                f"{monte['trades_per_run']} trades",
                f"Median return       {_pct(monte.get('median_return'))}",
                f"5th / 95th pct      {_pct(monte.get('p05_return'))} / "
                f"{_pct(monte.get('p95_return'))}",
                f"Prob. profit        {_pct(monte.get('prob_profit'))}",
                f"Median max DD       {_pct(monte.get('median_max_drawdown'))}",
                f"Median worst streak {_num(monte.get('median_worst_streak'), 1)}",
            ]
        )
    return lines


def format_summary(result: BacktestResult) -> str:
    m = result.metrics
    lines = [
        f"Backtest: {result.symbol} {result.timeframe} | strategy={result.strategy or 'n/a'}",
        "-" * 64,
        f"Initial balance     {_num(result.initial_balance)}",
        f"Final equity        {_num(result.final_balance)}",
        f"Total return        {_pct(m.get('total_return'))}",
        f"CAGR                {_pct(m.get('cagr'))}",
        f"Sharpe              {_num(m.get('sharpe'))}",
        f"Sortino             {_num(m.get('sortino'))}",
        f"Max drawdown        {_pct(m.get('max_drawdown'))}",
        f"Calmar              {_num(m.get('calmar'))}",
        "-" * 64,
        f"Trades              {m.get('trades', 0)}",
        f"Win rate            {_pct(m.get('win_rate'))}",
        f"Profit factor       {_num(m.get('profit_factor'))}",
        f"Expectancy          {_num(m.get('expectancy'))}",
        f"Avg win / loss      {_num(m.get('avg_win'))} / {_num(m.get('avg_loss'))}",
        f"Payoff ratio        {_num(m.get('payoff_ratio'))}",
        f"Total pips          {_num(m.get('total_pips'), 1)}",
        f"Long / short        {m.get('long_trades', 0)} / {m.get('short_trades', 0)}",
    ]
    lines.extend(_analysis_lines(getattr(result, "analysis", None)))
    lines.append("-" * 64)
    return "\n".join(lines)


def format_walkforward_summary(result: Any) -> str:
    m = result.metrics
    lines = [
        f"Walk-forward: {result.symbol} {result.timeframe} | "
        f"strategy={result.strategy}",
        "-" * 64,
        f"Windows             {len(result.windows)}",
        f"Initial balance     {_num(result.initial_balance)}",
        f"Final equity        {_num(result.final_balance)}",
        f"Total return        {_pct(m.get('total_return'))}",
        f"CAGR                {_pct(m.get('cagr'))}",
        f"Sharpe              {_num(m.get('sharpe'))}",
        f"Sortino             {_num(m.get('sortino'))}",
        f"Max drawdown        {_pct(m.get('max_drawdown'))}",
        f"Trades              {m.get('trades', 0)}",
        f"Win rate            {_pct(m.get('win_rate'))}",
        f"Profit factor       {_num(m.get('profit_factor'))}",
        f"Expectancy          {_num(m.get('expectancy'))}",
    ]
    lines.extend(_analysis_lines(getattr(result, "analysis", None)))
    lines.extend(["-" * 64, "Windows (out-of-sample):"])
    for window in result.windows:
        params = ", ".join(
            f"{key}={value}" for key, value in window.get("params", {}).items()
        )
        lines.append(
            f"  W{window['window']:>2} "
            f"{str(window['test_start'])[:10]}..{str(window['test_end'])[:10]} "
            f"ret {_pct(window.get('test_return'))} "
            f"trades {window.get('test_trades', 0):>3} | {params}"
        )
    return "\n".join(lines)


def save_outputs(
    result: BacktestResult,
    output_dir: str | Path = "reports",
    plot: bool = False,
) -> dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"{result.symbol}_{result.timeframe}_{result.strategy or 'strategy'}"

    trades_path = out / f"{stem}_trades.csv"
    result.trades.to_csv(trades_path, index=False)

    equity_path = out / f"{stem}_equity.csv"
    result.equity.to_csv(equity_path, index_label="time")

    summary_path = out / f"{stem}_summary.json"
    summary_path.write_text(
        json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
    )

    paths = {
        "trades": trades_path,
        "equity": equity_path,
        "summary": summary_path,
    }

    if plot:
        chart_path = out / f"{stem}_equity.png"
        if plot_equity(result, chart_path):
            paths["chart"] = chart_path

    return paths


def plot_equity(result: BacktestResult, path: str | Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False

    figure, axis = plt.subplots(figsize=(10, 4.5))
    axis.plot(result.equity.index, result.equity.values, color="#1f77b4", linewidth=1.2)
    axis.set_title(f"{result.symbol} {result.timeframe} - {result.strategy}")
    axis.set_ylabel("Equity")
    axis.grid(True, alpha=0.3)
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)
    return True
