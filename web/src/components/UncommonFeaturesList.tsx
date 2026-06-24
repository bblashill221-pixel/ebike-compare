import { groupFeatures } from "../uncommonFeatures";

/** A bike's special features, grouped (🔒 Security & Tracking, …) with empty groups
 *  hidden. Renders "—" when the bike has none. Group headers are a larger font than the
 *  entries beneath them. Shared by the detail card and the compare page. */
export function UncommonFeaturesList({ features }: { features: string[] | undefined }) {
  const groups = groupFeatures(features);
  if (!groups.length) return <span className="text-xs text-slate-400">—</span>;
  return (
    <div className="space-y-2.5">
      {groups.map((g) => (
        <div key={g.label}>
          <div className="text-sm font-semibold text-slate-700">
            {g.emoji} {g.label}
          </div>
          <div className="text-xs text-slate-600">{g.items.join(" · ")}</div>
        </div>
      ))}
    </div>
  );
}

/** Standalone "Special Features" card (detail page) — hidden when the bike has none. */
export function SpecialFeaturesCard({ features }: { features: string[] | undefined }) {
  if (!groupFeatures(features).length) return null;
  return (
    <div className="card p-4">
      <h3 className="mb-3 font-semibold text-slate-800">Special Features</h3>
      <UncommonFeaturesList features={features} />
    </div>
  );
}
