import { useState } from "react";
import { titleCase } from "../format";
import type { Model } from "../types";
import { ValueScoreDebug } from "./ValueScoreDebug";

// Canonical dimension order. Each is an INDEPENDENT 0–100 aid ranked against the
// bike's PRIMARY-TYPE peers (not the whole fleet); "feature" is rarity-weighted
// equipment breadth. There is deliberately no composite/overall score (project
// rule), so never sum/average them.
export const SCORE_ORDER = [
  "power",
  "torque",
  "range",
  "battery",
  "weight",
  "price",
  "value",
];

// Single-hue (brand) intensity ramp: same color family throughout, deeper = higher.
// Color carries the same neutral magnitude signal as the bar's width -- never a
// good/bad value judgment (a low score just means "low for its peer group", e.g.
// light weight or low price). Deliberately no green/amber/red traffic light.
function barColor(v: number): string {
  if (v >= 75) return "bg-brand-600";
  if (v >= 50) return "bg-brand-500";
  if (v >= 25) return "bg-brand-400";
  return "bg-brand-300";
}

export function ScoreBars({ scores, model }: { scores: Record<string, number>; model?: Model }) {
  const keys = SCORE_ORDER.filter((k) => scores[k] != null);
  const [showValueDebug, setShowValueDebug] = useState(false);
  // DEV ONLY: clicking the `value` bar opens the score-input breakdown. import.meta.env.DEV
  // is statically false in prod, so the popup + its handler tree-shake away for users.
  const debuggable = (k: string) => import.meta.env.DEV && k === "value" && !!model;
  return (
    <div className="space-y-2">
      {keys.map((k) => {
        const v = Math.max(0, Math.min(100, scores[k] ?? 0));
        const dev = debuggable(k);
        return (
          <div
            key={k}
            className={`flex items-center gap-3 ${dev ? "cursor-pointer rounded outline-dashed outline-1 outline-transparent hover:outline-amber-400" : ""}`}
            onClick={dev ? () => setShowValueDebug(true) : undefined}
            title={dev ? "dev: show value-score inputs" : undefined}
          >
            <div className="w-24 shrink-0 text-xs font-medium text-slate-600">
              {titleCase(k)}
              {dev && <span className="ml-1 text-amber-500">⚙</span>}
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
      {showValueDebug && model && (
        <ValueScoreDebug model={model} onClose={() => setShowValueDebug(false)} />
      )}
    </div>
  );
}
