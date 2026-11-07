import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { EquityChart } from "../components/EquityChart";
import { MetricGrid } from "../components/MetricGrid";
import { StatusBanner } from "../components/StatusBanner";
import type { BacktestResult, Meta } from "../types";
import { useJob } from "../useJob";

type FormState = {
  symbol: string;
  timeframe: string;
  strategy: string;
  start: string;
  balance: string;
  spread: string;
  slippage: string;
  monteCarlo: string;
  save: boolean;
};

const INITIAL: FormState = {
  symbol: "EURUSD",
  timeframe: "4h",
  strategy: "trend_ma",
  start: "",
  balance: "",
  spread: "",
  slippage: "",
  monteCarlo: "500",
  save: false,
};

export function BacktestPanel({ meta }: { meta: Meta | null }) {
  const [form, setForm] = useState<FormState>(INITIAL);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { job, error, start } = useJob<BacktestResult>("backtest");

  const update = (patch: Partial<FormState>) =>
    setForm((previous) => ({ ...previous, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitError(null);
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        symbol: form.symbol,
        timeframe: form.timeframe,
        strategy: form.strategy,
        save: form.save,
      };
      if (form.start) payload.start = form.start;
      if (form.balance) payload.balance = Number(form.balance);
      if (form.spread) payload.spread = Number(form.spread);
      if (form.slippage) payload.slippage = Number(form.slippage);
      if (form.monteCarlo) payload.monte_carlo = Number(form.monteCarlo);

      const response = await api.backtest(payload);
      start(response.job_id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const result = job?.status === "succeeded" ? job.result : null;

  return (
    <section className="panel">
      <header className="panel-head">
        <div>
          <h2>Backtest</h2>
          <p className="muted">
            Event-driven simulation with ATR stops, risk sizing, benchmark and
            Monte Carlo analysis.
          </p>
        </div>
      </header>

      <form className="form" onSubmit={submit}>
        <label>
          <span>Symbol</span>
          <select
            value={form.symbol}
            onChange={(event) => update({ symbol: event.target.value })}
          >
            {(meta?.symbols ?? ["EURUSD"]).map((symbol) => (
              <option key={symbol} value={symbol}>
                {symbol}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Timeframe</span>
          <select
            value={form.timeframe}
            onChange={(event) => update({ timeframe: event.target.value })}
          >
            {(meta?.timeframes ?? ["1h", "4h", "1d"]).map((timeframe) => (
              <option key={timeframe} value={timeframe}>
                {timeframe}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Strategy</span>
          <select
            value={form.strategy}
            onChange={(event) => update({ strategy: event.target.value })}
          >
            {(meta?.strategies ?? ["trend_ma", "breakout", "mean_reversion", "composite"]).map(
              (strategy) => (
                <option key={strategy} value={strategy}>
                  {strategy}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          <span>Start (optional)</span>
          <input
            value={form.start}
            placeholder="2025-01-01"
            onChange={(event) => update({ start: event.target.value })}
          />
        </label>
        <label>
          <span>Balance</span>
          <input
            type="number"
            value={form.balance}
            placeholder="10000"
            onChange={(event) => update({ balance: event.target.value })}
          />
        </label>
        <label>
          <span>Spread (pips)</span>
          <input
            type="number"
            step="0.1"
            value={form.spread}
            placeholder="from config"
            onChange={(event) => update({ spread: event.target.value })}
          />
        </label>
        <label>
          <span>Slippage (pips)</span>
          <input
            type="number"
            step="0.1"
            value={form.slippage}
            placeholder="from config"
            onChange={(event) => update({ slippage: event.target.value })}
          />
        </label>
        <label>
          <span>Monte Carlo runs</span>
          <input
            type="number"
            min="0"
            value={form.monteCarlo}
            onChange={(event) => update({ monteCarlo: event.target.value })}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.save}
            onChange={(event) => update({ save: event.target.checked })}
          />
          <span>Save reports</span>
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Run backtest"}
        </button>
      </form>

      {submitError ? <div className="banner error">{submitError}</div> : null}
      {job ? <StatusBanner status={job.status} error={job.error ?? error} /> : null}

      {result ? (
        <div className="results">
          <div className="results-head">
            <h3>
              {result.symbol} {result.timeframe} · {result.strategy}
            </h3>
            <span className="muted">
              {result.bars} bars · {result.start} → {result.end}
            </span>
          </div>

          <MetricGrid
            metrics={result.metrics}
            keys={[
              "total_return",
              "cagr",
              "sharpe",
              "sortino",
              "max_drawdown",
              "calmar",
              "trades",
              "win_rate",
              "profit_factor",
              "expectancy",
            ]}
          />

          {result.analysis?.comparison ? (
            <>
              <h3>Benchmark</h3>
              <MetricGrid
                metrics={result.analysis.comparison}
                keys={["strategy_return", "buy_hold_return", "excess_return"]}
                columns={3}
              />
            </>
          ) : null}

          {result.analysis?.monte_carlo ? (
            <>
              <h3>Monte Carlo</h3>
              <MetricGrid
                metrics={result.analysis.monte_carlo}
                keys={[
                  "iterations",
                  "trades_per_run",
                  "median_return",
                  "p05_return",
                  "p95_return",
                  "prob_profit",
                  "median_max_drawdown",
                  "median_worst_streak",
                ]}
              />
            </>
          ) : null}

          <h3>Equity</h3>
          <EquityChart points={result.equity} />

          <h3>Trades</h3>
          <DataTable
            rows={result.trades}
            columns={[
              "ticket",
              "side",
              "volume",
              "entry_time",
              "entry_price",
              "exit_time",
              "exit_price",
              "profit",
              "pips",
              "reason",
            ]}
            empty="No trades were generated."
          />

          {result.paths ? (
            <p className="muted">
              Saved: {Object.values(result.paths).join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
