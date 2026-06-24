import type { Analysis, Model } from "../types";
import { ScoreBars } from "./ScoreBars";

export function ScorePanel({ analysis, model }: { analysis: Analysis; model?: Model }) {
  const type = analysis.primary_type;
  // Standout badges live in the page header (the "features" row); ScorePanel is just
  // the dimension scores so the two don't duplicate on the detail page.
  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h3 className="font-semibold text-slate-800">Dimension Scores</h3>
        <span className="text-xs text-slate-400">
          0–100{type ? ` vs ${type} bikes` : ""}
        </span>
      </div>
      <ScoreBars scores={analysis.scores ?? {}} model={model} />
      <p className="text-xs text-slate-400">
        Each score is an independent aid, ranked against this bike's same-type peers.
        There is no overall score — weigh the categories that matter to you.
      </p>
    </div>
  );
}
