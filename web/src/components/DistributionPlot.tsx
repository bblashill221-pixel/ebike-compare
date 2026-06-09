import type { StatDist } from "../types";
import { formatNumber } from "../format";

interface Props {
  stat: StatDist;
  value?: number | null;
  unit?: string;
}

// Compact percentile plot: a min–max track with p10–p90 band, p50 line, and an
// optional marker for one bike's value.
export function DistributionPlot({ stat, value, unit }: Props) {
  const { min, p10, p50, p90, max } = stat;
  const span = max - min || 1;
  const pct = (v: number) => `${((Math.max(min, Math.min(max, v)) - min) / span) * 100}%`;
  // currency units prefix ("$1,095"); everything else suffixes ("500 Wh")
  const fmt = (v: number) =>
    unit === "$" ? `$${formatNumber(v)}` : `${formatNumber(v)}${unit ?? ""}`;
  return (
    <div>
      <div className="relative h-6">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-200" />
        <div
          className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-brand-100"
          style={{ left: pct(p10), width: `calc(${pct(p90)} - ${pct(p10)})` }}
        />
        <div
          className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 bg-brand-600"
          style={{ left: pct(p50) }}
          title={`median ${formatNumber(p50)}`}
        />
        {value != null && Number.isFinite(value) && (
          <div
            className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-500 shadow"
            style={{ left: pct(value) }}
            title={`this bike: ${formatNumber(value)}`}
          />
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>{fmt(min)}</span>
        <span>median {fmt(p50)}</span>
        <span>{fmt(max)}</span>
      </div>
    </div>
  );
}
