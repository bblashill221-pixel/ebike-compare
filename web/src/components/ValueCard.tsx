import { useState } from "react";
import type { Model } from "../types";
import { ValueScoreDebug } from "./ValueScoreDebug";

/** The Value dimension on its own card — split out from the dimension-score panel
 *  (the other dimensions now live in the "How It Compares" table). Value is special:
 *  it's parts-per-dollar, ranked within the bike's type, with no good/bad traffic light. */
export function ValueCard({ model }: { model: Model }) {
  const [showDebug, setShowDebug] = useState(false);
  const score = model.analysis?.scores?.value;
  const ratio = model.analysis?.component_quality?.value_ratio;
  const type = model.analysis?.primary_type;
  if (score == null && ratio == null) return null;
  // DEV ONLY: click opens the value-score input breakdown (tree-shaken from prod).
  const dev = import.meta.env.DEV;
  const w = score == null ? 0 : Math.max(0, Math.min(100, score));
  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold text-slate-800">Value</h3>
        <span className="shrink-0 text-xs text-slate-400">parts per dollar</span>
      </div>
      {score != null && (
        <div
          className={`mt-3 flex items-center gap-3 ${dev ? "cursor-pointer rounded outline-dashed outline-1 outline-transparent hover:outline-amber-400" : ""}`}
          onClick={dev ? () => setShowDebug(true) : undefined}
          title={dev ? "dev: show value-score inputs" : undefined}
        >
          <div className="w-24 shrink-0 text-xs font-medium text-slate-600">
            Value score{dev && <span className="ml-1 text-amber-500">⚙</span>}
          </div>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${w}%` }} />
          </div>
          <div className="w-8 shrink-0 text-right text-xs tabular-nums text-slate-500">{Math.round(score)}</div>
        </div>
      )}
      {ratio != null && (
        <p className="mt-3 text-xs text-slate-500">
          Priced at <strong>{ratio.toFixed(2)}×</strong> its parts' estimated retail value
          {type ? <> — ranked within {type} bikes</> : null}. Lower means more bike per dollar.
        </p>
      )}
      <p className="mt-2 text-xs text-slate-400">
        An independent aid (0–100), ranked within this bike's type. There is no overall score.
      </p>
      {showDebug && <ValueScoreDebug model={model} onClose={() => setShowDebug(false)} />}
    </div>
  );
}
