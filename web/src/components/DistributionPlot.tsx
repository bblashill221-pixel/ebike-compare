import type { StatDist } from "../types";
import { formatNumber } from "../format";

interface Props {
  stat: StatDist;
  value?: number | null;
  unit?: string;
  /** true when LOWER is better for this metric (price, weight) -> drives the
   *  green/red of the model-vs-median difference. Default: higher is better. */
  lowerBetter?: boolean;
}

// Compact percentile plot: a min–max track with a median tick and an optional
// green marker for one bike's value, over a Min / Median / Max captioned footer.
// When a value is given, the signed model-vs-median difference is overlaid on the
// track at the midpoint between the marker and the median tick (green = better).
export function DistributionPlot({ stat, value, unit, lowerBetter = false }: Props) {
  const { min, p50, max } = stat;
  const span = max - min || 1;
  const clampPct = (v: number) => ((Math.max(min, Math.min(max, v)) - min) / span) * 100;
  const pct = (v: number) => `${clampPct(v)}%`;
  // currency units prefix ("$1,095"); everything else suffixes ("500 Wh")
  const fmt = (v: number) =>
    unit === "$" ? `$${formatNumber(v)}` : `${formatNumber(v)}${unit ?? ""}`;
  const Stop = ({ v, label, align }: { v: number; label: string; align: string }) => (
    <div className={align}>
      <div className="font-semibold text-slate-700">{fmt(v)}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  );

  // signed difference vs the median, formatted with sign + unit ("+188 Wh", "-$300")
  const hasValue = value != null && Number.isFinite(value);
  let diffLabel = "";
  let diffColor = "text-slate-400";
  let diffMid = 50;
  if (hasValue) {
    const diff = (value as number) - p50;
    const sign = diff > 0 ? "+" : diff < 0 ? "-" : "";
    const mag = unit === "$"
      ? `$${formatNumber(Math.abs(diff))}`
      : `${formatNumber(Math.abs(diff))}${unit ?? ""}`;
    diffLabel = `${sign}${mag}`;
    const better = lowerBetter ? diff < 0 : diff > 0;
    diffColor = diff === 0 ? "text-slate-400" : better ? "text-emerald-600" : "text-rose-600";
    diffMid = (clampPct(value as number) + clampPct(p50)) / 2;
  }

  return (
    <div>
      <div className="relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-100" />
        <div
          className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 bg-brand-500"
          style={{ left: pct(p50) }}
          title={`median ${formatNumber(p50)}`}
        />
        {hasValue && (
          <div
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-500 shadow"
            style={{ left: pct(value as number) }}
            title={`this bike: ${formatNumber(value as number)}`}
          />
        )}
        {hasValue && diffLabel && (
          <div
            className={`absolute top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded bg-white px-1 text-[10px] font-semibold leading-none ${diffColor}`}
            style={{ left: `${diffMid}%` }}
          >
            {diffLabel}
          </div>
        )}
      </div>
      <div className="mt-1.5 flex items-start justify-between text-[11px]">
        <Stop v={min} label="Min" align="text-left" />
        <Stop v={p50} label="Median" align="text-center" />
        <Stop v={max} label="Max" align="text-right" />
      </div>
    </div>
  );
}
