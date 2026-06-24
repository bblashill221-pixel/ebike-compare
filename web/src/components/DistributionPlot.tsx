import type { StatDist } from "../types";
import { formatNumber } from "../format";

interface Props {
  stat: StatDist;
  value?: number | null;
  unit?: string;
}

// Compact percentile plot: a min–max track with a median tick and an optional
// green marker for one bike's value, over a Min / Median / Max captioned footer.
// The bike's own value is shown in the parent card header, not here.
export function DistributionPlot({ stat, value, unit }: Props) {
  const { min, p50, max } = stat;
  const span = max - min || 1;
  const pct = (v: number) => `${((Math.max(min, Math.min(max, v)) - min) / span) * 100}%`;
  // currency units prefix ("$1,095"); everything else suffixes ("500 Wh")
  const fmt = (v: number) =>
    unit === "$" ? `$${formatNumber(v)}` : `${formatNumber(v)}${unit ?? ""}`;
  const Stop = ({ v, label, align }: { v: number; label: string; align: string }) => (
    <div className={align}>
      <div className="font-semibold text-slate-700">{fmt(v)}</div>
      <div className="text-[11px] text-slate-400">{label}</div>
    </div>
  );
  return (
    <div>
      <div className="relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-100" />
        <div
          className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 bg-brand-500"
          style={{ left: pct(p50) }}
          title={`median ${formatNumber(p50)}`}
        />
        {value != null && Number.isFinite(value) && (
          <div
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-emerald-500 shadow"
            style={{ left: pct(value) }}
            title={`this bike: ${formatNumber(value)}`}
          />
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
