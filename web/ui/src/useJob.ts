import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { Job } from "./types";

export function useJob<T>(kind: "backtest" | "walkforward") {
  const [job, setJob] = useState<Job<T> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  const clearTimer = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  const poll = useCallback(
    async (id: string) => {
      try {
        const next =
          kind === "backtest"
            ? await api.backtestJob(id)
            : await api.walkforwardJob(id);
        setJob(next as Job<T>);
        if (next.status === "queued" || next.status === "running") {
          timer.current = window.setTimeout(() => {
            void poll(id);
          }, 1000);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    },
    [kind],
  );

  const start = useCallback(
    (id: string) => {
      clearTimer();
      setError(null);
      setJob(null);
      void poll(id);
    },
    [clearTimer, poll],
  );

  const reset = useCallback(() => {
    clearTimer();
    setJob(null);
    setError(null);
  }, [clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  return { job, error, start, reset };
}
