import { useId } from "react";

import { formatMoney, formatTime } from "../format";
import type { EquityPoint } from "../types";

type Props = {
  points: EquityPoint[];
  title?: string;
};

export function EquityChart({ points, title = "Equity" }: Props) {
  const gradientId = useId();

  if (points.length < 2) {
    return <div className="empty">Not enough equity points to chart.</div>;
  }

  const width = 760;
  const height = 260;
  const pad = 18;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;

  const x = (index: number) =>
    pad + (index / (points.length - 1)) * (width - pad * 2);
  const y = (value: number) =>
    height - pad - ((value - min) / span) * (height - pad * 2);

  const line = points
    .map((point, index) => {
      const prefix = index === 0 ? "M" : "L";
      return `${prefix}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`;
    })
    .join(" ");

  const area = `${line} L${x(points.length - 1).toFixed(1)},${height - pad} L${x(0).toFixed(1)},${height - pad} Z`;

  const first = points[0].value;
  const last = points[points.length - 1].value;
  const rising = last >= first;
  const color = rising ? "#22c55e" : "#ef4444";

  return (
    <div className="chart">
      <div className="chart-head">
        <span>{title}</span>
        <span className={rising ? "pos" : "neg"}>
          {formatMoney(first)} → {formatMoney(last)}
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.35" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill={`url(#${gradientId})`} />
        <path d={line} fill="none" stroke={color} strokeWidth="2" />
      </svg>
      <div className="chart-foot">
        <span>{formatTime(points[0].time)}</span>
        <span>{formatTime(points[points.length - 1].time)}</span>
      </div>
    </div>
  );
}
