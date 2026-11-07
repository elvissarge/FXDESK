export type EquityPoint = { time: string; value: number };

export type Trade = Record<string, unknown>;

export type Metrics = Record<string, number | null>;

export type Analysis = {
  buy_hold?: Metrics;
  comparison?: {
    strategy_return?: number;
    buy_hold_return?: number;
    excess_return?: number;
  };
  monte_carlo?: Metrics & { iterations?: number; trades_per_run?: number };
};

export type BacktestResult = {
  symbol: string;
  timeframe: string;
  strategy: string;
  bars: number;
  start: string;
  end: string;
  summary: string;
  metrics: Metrics;
  analysis: Analysis;
  equity: EquityPoint[];
  trades: Trade[];
  final_balance: number;
  initial_balance: number;
  paths?: Record<string, string>;
};

export type WalkForwardWindow = {
  window: number;
  train_start: string;
  train_end: string;
  test_start: string;
  test_end: string;
  params: Record<string, unknown>;
  train_score: number;
  train_trades: number;
  test_return: number;
  test_trades: number;
  test_sharpe: number;
};

export type WalkForwardResult = BacktestResult & {
  windows: WalkForwardWindow[];
};

export type JobStatus = "queued" | "running" | "succeeded" | "failed";

export type Job<T = unknown> = {
  id: string;
  kind: string;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  params: Record<string, unknown>;
  result: T | null;
  error: string | null;
};

export type Plan = Record<string, unknown>;

export type SignalsResult = {
  symbols: string[];
  timeframe: string;
  strategies: string[];
  live: boolean;
  count: number;
  plans: Plan[];
};

export type PaperStatus = {
  running: boolean;
  state_file: string;
  account: {
    balance: number;
    equity: number;
    realized_pnl: number;
    currency: string;
  };
  positions: Record<string, unknown>[];
  closed: Record<string, unknown>[];
  closed_count: number;
  cycles: number;
  last_cycle: string | null;
  error: string | null;
  params: Record<string, unknown> | null;
};

export type Meta = {
  version: string;
  strategies: string[];
  timeframes: string[];
  symbols: string[];
  providers: Record<string, boolean>;
  account: Record<string, unknown>;
  backtest: Record<string, unknown>;
  walkforward: Record<string, unknown>;
  paper: Record<string, unknown>;
  strategy_params: Record<string, Record<string, unknown>>;
};
