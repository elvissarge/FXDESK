import type {
  BacktestResult,
  Job,
  Meta,
  PaperStatus,
  SignalsResult,
  WalkForwardResult,
} from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

type RequestOptions = {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method: options.method ?? "GET",
    headers:
      options.body !== undefined ? { "content-type": "application/json" } : undefined,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
    signal: options.signal,
  });

  const text = await response.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" && data !== null && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `${response.status} ${response.statusText}`;
    throw new Error(detail);
  }

  return data as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  symbols: () => request<Record<string, unknown>[]>("/api/symbols"),

  backtest: (body: Record<string, unknown>) =>
    request<{ job_id: string; status: string }>("/api/backtest", {
      method: "POST",
      body,
    }),

  walkforward: (body: Record<string, unknown>) =>
    request<{ job_id: string; status: string }>("/api/walkforward", {
      method: "POST",
      body,
    }),

  job: <T = unknown>(id: string) => request<Job<T>>(`/api/jobs/${id}`),

  backtestJob: (id: string) => request<Job<BacktestResult>>(`/api/jobs/${id}`),
  walkforwardJob: (id: string) =>
    request<Job<WalkForwardResult>>(`/api/jobs/${id}`),

  signals: (body: Record<string, unknown>) =>
    request<SignalsResult>("/api/signals", { method: "POST", body }),

  paperStatus: (stateFile?: string) =>
    request<PaperStatus>(
      `/api/paper/status${stateFile ? `?state_file=${encodeURIComponent(stateFile)}` : ""}`,
    ),

  paperStart: (body: Record<string, unknown>) =>
    request<PaperStatus>("/api/paper/start", { method: "POST", body }),

  paperStop: () => request<PaperStatus>("/api/paper/stop", { method: "POST" }),

  paperCycle: (body: Record<string, unknown>) =>
    request<{ opened: Record<string, unknown>[]; status: PaperStatus }>(
      "/api/paper/cycle",
      { method: "POST", body },
    ),

  paperReset: (stateFile?: string) =>
    request<{ state_file: string; removed: boolean }>("/api/paper/reset", {
      method: "POST",
      body: { state_file: stateFile ?? null },
    }),
};
