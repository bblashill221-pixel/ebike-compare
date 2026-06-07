import { titleCase } from "../format";

// Canonical dimension order. These are INDEPENDENT 0–100 comparison aids — there is
// deliberately no composite/overall score (project rule), so never sum/average them.
export const SCORE_ORDER = [
  "power",
  "range",
  "battery",
  "components",
  "safety",
  "security",
  "tech",
  "warranty",
  "value",
];

function barColor(v: number): string {
  if (v >= 75) return "bg-emerald-500";
  if (v >= 50) return "bg-brand-500";
  if (v >= 25) return "bg-amber-500";
  return "bg-rose-400";
}

export function ScoreBars({ scores }: { scores: Record<string, number> }) {
  const keys = SCORE_ORDER.filter((k) => k in scores);
  return (
    <div className="space-y-2">
      {keys.map((k) => {
        const v = Math.max(0, Math.min(100, scores[k] ?? 0));
        return (
          <div key={k} className="flex items-center gap-3">
            <div className="w-24 shrink-0 text-xs font-medium text-slate-600">
              {titleCase(k)}
            </div>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${barColor(v)}`} style={{ width: `${v}%` }} />
            </div>
            <div className="w-8 shrink-0 text-right text-xs tabular-nums text-slate-500">
              {Math.round(v)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
