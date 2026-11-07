import type { JobStatus } from "../types";

type Props = {
  status: JobStatus;
  error?: string | null;
};

export function StatusBanner({ status, error }: Props) {
  if (status === "failed") {
    return <div className="banner error">Job failed: {error ?? "unknown error"}</div>;
  }
  if (status === "queued" || status === "running") {
    return (
      <div className="banner">
        <span className="spinner" />
        {status === "queued" ? "Queued…" : "Running…"}
      </div>
    );
  }
  return null;
}
