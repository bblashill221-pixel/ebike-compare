import type { Model } from "../types";

// Coarse component BUILD GRADE badge (Budget/Standard/Enhanced/Premium). The premium
// components themselves live in Highlights — this is just the one-word quality tier, used
// (with the typical-price context) to explain WHY a bike's value score is what it is.
const TIER_STYLE: Record<string, string> = {
  Premium: "bg-violet-100 text-violet-700 ring-violet-200",
  Enhanced: "bg-sky-100 text-sky-700 ring-sky-200",
  Standard: "bg-emerald-100 text-emerald-700 ring-emerald-200",
  Budget: "bg-slate-100 text-slate-600 ring-slate-200",
};

export function BuildGrade({ model }: { model: Model }) {
  const tier = model.analysis?.specs_typed?.build_tier;
  if (!tier) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${
        TIER_STYLE[tier] ?? TIER_STYLE.Budget
      }`}
    >
      {tier} build
    </span>
  );
}
