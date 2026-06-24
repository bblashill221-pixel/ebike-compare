import { Fragment } from "react";

// "Standout Features" sub-header + a two-column key/value list — one standout per line,
// "[feature]  [value]", as many lines as there are standouts. Magnitude specs carry their
// figure; uncommon-equipment features have no value and show "✓". Renders nothing (no
// sub-header) when there are no standouts.
export function StandoutFeatures({
  standouts,
}: {
  standouts?: { label: string; value?: string }[];
}) {
  if (!standouts || standouts.length === 0) return null;
  return (
    <div>
      <h3 className="mb-1 text-center text-xs font-semibold text-slate-700">Highlights</h3>
      <div className="mx-auto grid w-max grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        {standouts.map((s) => (
          <Fragment key={s.label}>
            <div className="whitespace-nowrap text-xs text-slate-800">{s.label}</div>
            <div className="whitespace-nowrap text-xs text-slate-500">{s.value || "✓"}</div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
