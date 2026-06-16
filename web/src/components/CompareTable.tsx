import type { Model, SpecValue } from "../types";
import { fieldLabel, formatSpecValue, titleCase, withUnit } from "../format";

const GROUP_ORDER = [
  "general_info",
  "ebike_system",
  "safety",
  "certifications",
  "water_resistance",
  "frameset",
  "drivetrain",
  "brakes",
  "wheelset",
  "cockpit",
  "geometry",
  "included_accessories",
];

function fieldKeys(models: Model[], group: string): string[] {
  const seen: string[] = [];
  for (const m of models) {
    for (const k of Object.keys(m.specs?.[group] ?? {})) {
      if (!seen.includes(k)) seen.push(k);
    }
  }
  return seen;
}

function cell(m: Model, group: string, field: string): string {
  const v = m.specs?.[group]?.[field] as SpecValue | undefined;
  if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) return "—";
  return formatSpecValue(v);
}

export function CompareTable({ models }: { models: Model[] }) {
  return (
    <div className="space-y-6">
      {GROUP_ORDER.filter((g) => models.some((m) => m.specs?.[g] && Object.keys(m.specs[g]).length)).map((group) => {
        const keys = fieldKeys(models, group);
        if (!keys.length) return null;
        return (
          <div key={group} className="card overflow-hidden">
            <h3 className="border-b border-slate-100 bg-slate-50 px-4 py-2 font-semibold text-slate-800">
              {titleCase(group)}
            </h3>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-slate-100">
                {keys.map((field) => {
                  const { label, unit } = fieldLabel(field);
                  const values = models.map((m) => withUnit(cell(m, group, field), unit));
                  const differ = new Set(values.filter((v) => v !== "—")).size > 1;
                  return (
                    <tr key={field} className="align-top">
                      <th className="w-40 bg-slate-50/50 px-4 py-2 text-left font-medium text-slate-500">
                        {label}
                      </th>
                      {values.map((v, i) => (
                        <td
                          key={i}
                          className={`px-4 py-2 text-slate-800 ${differ ? "bg-amber-50/60" : ""}`}
                        >
                          {v}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        );
      })}
    </div>
  );
}
