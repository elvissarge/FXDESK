import { formatMetric, humanize } from "../format";

type Props = {
  metrics: Record<string, unknown>;
  keys?: string[];
  columns?: number;
};

export function MetricGrid({ metrics, keys, columns = 4 }: Props) {
  const entries = keys
    ? keys
        .filter((key) => key in metrics)
        .map((key) => [key, metrics[key]] as const)
    : Object.entries(metrics).filter(([, value]) => value !== null && value !== undefined);

  if (entries.length === 0) {
    return null;
  }

  return (
    <div
      className="metrics"
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {entries.map(([key, value]) => (
        <div className="metric" key={key}>
          <span className="metric-label">{humanize(key)}</span>
          <span className="metric-value">{formatMetric(key, value)}</span>
        </div>
      ))}
    </div>
  );
}
