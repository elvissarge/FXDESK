import { useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api";
import { DataTable } from "../components/DataTable";
import { EquityChart } from "../components/EquityChart";
import { MetricGrid } from "../components/MetricGrid";
import { StatusBanner } from "../components/StatusBanner";
import { formatParams } from "../format";
import type { Meta, WalkForwardResult } from "../types";
import { useJob } from "../useJob";

type FormState = {
  symbol: string;
  timeframe: string;
  strategy: string;
  start: string;
  trainBars: string;
  testBars: string;
  stepBars: string;
  objective: string;
  monteCarlo: string;
  grid: string;
  save: boolean;
};

const INITIAL: FormState = {
  symbol: "EURUSD",
  timeframe: "4h",
  strategy: "trend_ma",
  start: "",
  trainBars: "",
  testBars: "",
  stepBars: "",
  objective: "",
  monteCarlo: "",
  grid: "",
  save: false,
};

export function WalkForwardPanel({ meta }: { meta: Meta | null }) {
  const [form, setForm] = useState<FormState>(INITIAL);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { job, error, start } = useJob<WalkForwardResult>("walkforward");

  const update = (patch: Partial<FormState>) =>
    setForm((previous) => ({ ...previous, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitError(null);

    let grid: unknown;
    if (form.grid.trim()) {
      try {
        grid = JSON.parse(form.grid);
      } catch {
        setSubmitError("Grid must be valid JSON, e.g. {\"fast\": [10, 20], \"slow\": [50, 100]}");
        return;
      }
    }

    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        symbol: form.symbol,
        timeframe: form.timeframe,
        strategy: form.strategy,
        save: form.save,
      };
      if (form.start) payload.start = form.start;
      if (form.trainBars) payload.train_bars = Number(form.trainBars);
      if (form.testBars) payload.test_bars = Number(form.testBars);
      if (form.stepBars) payload.step_bars = Number(form.stepBars);
      if (form.objective) payload.objective = form.objective;
      if (form.monteCarlo) payload.monte_carlo = Number(form.monteCarlo);
      if (grid !== undefined) payload.grid = grid;

      const response = await api.walkforward(payload);
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
          <h2>Walk-Forward</h2>
          <p className="muted">
            Rolling in-sample optimisation with out-of-sample validation of the
            selected parameters.
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
            placeholder="2024-01-01"
            onChange={(event) => update({ start: event.target.value })}
          />
        </label>
        <label>
          <span>Train bars</span>
          <input
            type="number"
            value={form.trainBars}
            placeholder="from config"
            onChange={(event) => update({ trainBars: event.target.value })}
          />
        </label>
        <label>
          <span>Test bars</span>
          <input
            type="number"
            value={form.testBars}
            placeholder="from config"
            onChange={(event) => update({ testBars: event.target.value })}
          />
        </label>
        <label>
          <span>Step bars</span>
          <input
            type="number"
            value={form.stepBars}
            placeholder="from config"
            onChange={(event) => update({ stepBars: event.target.value })}
          />
        </label>
        <label>
          <span>Objective</span>
          <input
            value={form.objective}
            placeholder="from config"
            onChange={(event) => update({ objective: event.target.value })}
          />
        </label>
        <label>
          <span>Monte Carlo runs</span>
          <input
            type="number"
            min="0"
            value={form.monteCarlo}
            placeholder="from config"
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
        <label className="wide">
          <span>Parameter grid (JSON, optional)</span>
          <textarea
            rows={3}
            value={form.grid}
            placeholder='{"fast": [10, 20], "slow": [50, 100]}'
            onChange={(event) => update({ grid: event.target.value })}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? "Submitting…" : "Run walk-forward"}
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
              {result.windows.length} windows · {result.start} → {result.end}
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

          <h3>Windows</h3>
          <DataTable
            rows={result.windows.map((window) => ({
              ...window,
              params: formatParams(window.params),
            }))}
            columns={[
              "window",
              "test_start",
              "test_end",
              "params",
              "train_score",
              "train_trades",
              "test_return",
              "test_trades",
              "test_sharpe",
            ]}
          />

          <h3>Out-of-sample equity</h3>
          <EquityChart points={result.equity} />

          <h3>Trades</h3>
          <DataTable
            rows={result.trades}
            columns={[
              "window",
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
            empty="No out-of-sample trades were generated."
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
