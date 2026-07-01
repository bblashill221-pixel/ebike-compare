import { Link } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { displayName } from "../components/BikeCard";
import { isAvailable } from "../soldOut";
import { formatPrice, titleCase } from "../format";
import type { Model } from "../types";

// Every IN-STOCK bike grouped by its primary eBike type, ranked by value score (parts-per-
// dollar, within type) in descending order — best value first. Sold-out bikes are excluded
// (they're not part of the rankings); bikes with no value score are omitted too.
export function ValueTable() {
  const { models, status } = useData();
  if (status === "loading")
    return <div className="mx-auto max-w-5xl px-4 py-10 text-slate-500">Loading…</div>;

  const score = (m: Model) => m.analysis?.scores?.value;
  const groups = new Map<string, Model[]>();
  for (const m of models) {
    const t = m.analysis?.primary_type;
    if (!t || score(m) == null || !isAvailable(m)) continue;
    let arr = groups.get(t);
    if (!arr) groups.set(t, (arr = []));
    arr.push(m);
  }
  const types = [...groups.keys()].sort();
  for (const t of types) groups.get(t)!.sort((a, b) => (score(b) ?? 0) - (score(a) ?? 0));

  // model names usually already include the brand; prepend it only when they don't.
  const fullName = (m: Model) =>
    displayName(m).toLowerCase().includes(m.brand.toLowerCase())
      ? displayName(m)
      : `${titleCase(m.brand)} ${displayName(m)}`;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="text-xl font-semibold text-slate-800">Value by eBike Type</h1>
      <p className="mb-6 mt-1 text-sm text-slate-500">
        Each type's bikes ranked by value score (parts-per-dollar, within type) — best value first.
      </p>
      {types.map((t) => {
        const rows = groups.get(t)!;
        return (
          <section key={t} className="mb-8">
            <h2 className="mb-2 font-semibold text-slate-700">
              {t} <span className="font-normal text-slate-400">({rows.length})</span>
            </h2>
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    <th className="w-10 px-3 py-2 text-right">#</th>
                    <th className="px-3 py-2 text-left">Model</th>
                    <th className="px-3 py-2 text-right">Value</th>
                    <th className="px-3 py-2 text-right">Price</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((m, i) => (
                    <tr key={m.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                      <td className="px-3 py-2 text-right tabular-nums text-slate-400">{i + 1}</td>
                      <td className="px-3 py-2">
                        <Link
                          to={`/bike/${encodeURIComponent(m.id)}`}
                          className="font-medium text-brand-700 hover:underline"
                        >
                          {fullName(m)}
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums font-semibold text-slate-700">
                        {Math.round(score(m)!)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-slate-600">
                        {formatPrice(m.price ?? m.price_min, m.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </div>
  );
}
