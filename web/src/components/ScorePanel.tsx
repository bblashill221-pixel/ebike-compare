import type { Analysis } from "../types";
import { ScoreBars } from "./ScoreBars";

export function ScorePanel({ analysis }: { analysis: Analysis }) {
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="font-semibold text-slate-800">Dimension scores</h3>
        <span className="text-xs text-slate-400">0–100, per category</span>
      </div>
      <ScoreBars scores={analysis.scores ?? {}} />
      <p className="text-xs text-slate-400">
        Each score is an independent, field-relative comparison aid. There is no overall
        score — weigh the categories that matter to you.
      </p>
      {analysis.highlights?.length > 0 && (
        <div className="flex flex-wrap gap-1 pt-1">
          {analysis.highlights.map((h) => (
            <span key={h} className="chip bg-emerald-50 text-emerald-700">
              {h}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
