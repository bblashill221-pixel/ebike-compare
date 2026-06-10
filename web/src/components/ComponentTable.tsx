import { titleCase, formatSpecValue, formatNumber } from "../format";
import { useUnits, type UnitSystem } from "../units";
import type { SpecValue } from "../types";
import { COLUMN_CONFIG, KIND_LABEL, type Column } from "./componentColumns";

/** One component instance (e.g. the front brake) plus its position label. */
export type ComponentInstance = { position: string | null; obj: Record<string, SpecValue> };

function rawValue(col: Column, obj: Record<string, SpecValue>): SpecValue {
  if (col.key === "__make") {
    const make = [obj.manufacturer, obj.model].filter((x) => x != null && x !== "").join(" ");
    return make || null;
  }
  return obj[col.key] ?? null;
}

function isEmpty(v: SpecValue): boolean {
  return v == null || v === "" || (Array.isArray(v) && v.length === 0);
}

function renderCell(col: Column, obj: Record<string, SpecValue>, units: UnitSystem): string {
  const v = rawValue(col, obj);
  if (isEmpty(v)) return "—";
  if (typeof v === "boolean") return v ? "✓" : "—";
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (typeof v === "number") return formatNumber(v, 2, false) + (col.unit ?? "");
  if (typeof v !== "string") return formatSpecValue(v, units); // nested object fallback
  if (col.key === "details" || col.key === "__make") return formatSpecValue(v, units);
  // short enum-ish tokens ("hub", "continuously_variable") get prettified
  const pretty = /^[a-z][a-z_]*$/.test(v) ? titleCase(v) : v;
  return pretty + (col.unit ?? "");
}

/** A parsed component kind rendered as a feature-column table: column headers are
 *  the component's features, one value row per instance (Front / Rear / single). */
export function ComponentTable({ kind, instances }: { kind: string; instances: ComponentInstance[] }) {
  const [units] = useUnits();
  const config = COLUMN_CONFIG[kind];
  if (!config || !instances.length) return null;
  // keep only columns that carry a value on at least one instance
  const cols = config.filter((col) => instances.some((inst) => !isEmpty(rawValue(col, inst.obj))));
  if (!cols.length) return null;
  const showPos = instances.length > 1;
  return (
    <div className="mb-3">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {KIND_LABEL[kind] ?? titleCase(kind)}
      </h3>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-medium text-slate-500">
              {showPos && <th className="py-1 pr-3" />}
              {cols.map((col) => (
                <th key={col.key} className="whitespace-nowrap py-1 pr-3">{col.header}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {instances.map((inst, i) => (
              <tr key={i} className="align-top">
                {showPos && (
                  <td className="whitespace-nowrap py-1 pr-3 font-medium text-slate-500">
                    {inst.position ?? "—"}
                  </td>
                )}
                {cols.map((col) => (
                  <td key={col.key} className="py-1 pr-3 text-slate-800">
                    {renderCell(col, inst.obj, units)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
