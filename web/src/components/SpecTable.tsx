import type { SpecGroup } from "../types";
import { formatSpecValue, hiddenUnitKeys, labelize } from "../format";
import { useUnits } from "../units";

function isEmpty(v: unknown): boolean {
  if (v == null || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v as object).length === 0;
  return false;
}

export function SpecTable({ group }: { group: SpecGroup }) {
  const [units] = useUnits();
  // drop the non-selected side of paired imperial/metric rows (weight_lb +
  // weight_kg, range_mi + range_km) so only the active system shows.
  const hide = hiddenUnitKeys(Object.keys(group), units);
  const rows = Object.entries(group).filter(([k, v]) => !isEmpty(v) && !hide.has(k));
  if (!rows.length) return null;
  return (
    <table className="w-full text-sm">
      <tbody className="divide-y divide-slate-100">
        {rows.map(([k, v]) => (
          <tr key={k} className="align-top">
            <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">
              {labelize(k)}
            </th>
            <td className="py-1.5 text-slate-800">{formatSpecValue(v, units)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
