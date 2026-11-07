const PERCENT_KEYS = new Set([
  "total_return",
  "cagr",
  "max_drawdown",
  "win_rate",
  "prob_profit",
  "median_return",
  "p05_return",
  "p95_return",
  "median_max_drawdown",
  "p05_max_drawdown",
  "excess_return",
  "buy_hold_return",
  "strategy_return",
  "test_return",
]);

export function humanize(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatNumber(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatMoney(value: number): string {
  if (!Number.isFinite(value)) return "n/a";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatMetric(key: string, value: unknown): string {
  if (value === null || value === undefined) return "n/a";
  if (typeof value !== "number" || !Number.isFinite(value)) return String(value);
  if (PERCENT_KEYS.has(key) || key.endsWith("_pct")) {
    return `${(value * 100).toFixed(2)}%`;
  }
  if (Number.isInteger(value)) return value.toLocaleString();
  return formatNumber(value, Math.abs(value) < 10 ? 3 : 2);
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") {
    return Number.isInteger(value) ? value.toLocaleString() : formatNumber(value, 4);
  }
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return formatTime(text);
  return text;
}

export function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([key, value]) => `${key}=${String(value)}`)
    .join(", ");
}
