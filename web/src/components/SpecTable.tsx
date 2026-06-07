import type { SpecGroup } from "../types";
import { formatSpecValue, labelize } from "../format";

function isEmpty(v: unknown): boolean {
  if (v == null || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v as object).length === 0;
  return false;
}

export function SpecTable({ group }: { group: SpecGroup }) {
  const rows = Object.entries(group).filter(([, v]) => !isEmpty(v));
  if (!rows.length) return null;
  return (
    <table className="w-full text-sm">
      <tbody className="divide-y divide-slate-100">
        {rows.map(([k, v]) => (
          <tr key={k} className="align-top">
            <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">
              {labelize(k)}
            </th>
            <td className="py-1.5 text-slate-800">{formatSpecValue(v)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
