import { titleCase, formatSpecValue, formatNumber } from "../format";
import { useUnits, type UnitSystem } from "../units";
import type { SpecValue } from "../types";
import { COLUMN_CONFIG, KIND_LABEL, type Column } from "./componentColumns";

/** One component instance (e.g. the front brake) plus its position label. */
export type ComponentInstance = { position: string | null; obj: Record<string, SpecValue> };

const _num = (x: SpecValue): number | null => (typeof x === "number" ? x : null);

/** Battery capacity as "720 Wh (48V × 15Ah)" -- Wh from the stated capacity or
 *  V×Ah, with the voltage/amp-hours folded in to save a row. Falls back to
 *  whichever parts exist. */
function batteryCapacity(obj: Record<string, SpecValue>): string {
  const v = _num(obj.voltage_v);
  const ah = _num(obj.amphours_ah);
  const wh = _num(obj.capacity_wh) ?? (v != null && ah != null ? Math.round(v * ah) : null);
  const parts: string[] = [];
  if (wh != null) parts.push(`${formatNumber(wh, 2, false)} Wh`);
  if (v != null && ah != null)
    parts.push(`(${formatNumber(v, 2, false)}V × ${formatNumber(ah, 2, false)}Ah)`);
  else if (v != null) parts.push(`${formatNumber(v, 2, false)}V`);
  else if (ah != null) parts.push(`${formatNumber(ah, 2, false)}Ah`);
  return parts.join(" ");
}

/** Motor power as "750/1188 W" (Nominal/Peak), or whichever single figure exists. */
function motorPower(obj: Record<string, SpecValue>): string {
  const nom = _num(obj.power_w), pk = _num(obj.peak_w);
  if (nom != null && pk != null) return `${formatNumber(nom, 2, false)}/${formatNumber(pk, 2, false)} W`;
  if (nom != null) return `${formatNumber(nom, 2, false)} W`;
  if (pk != null) return `${formatNumber(pk, 2, false)} W`;
  return "";
}

function rawValue(col: Column, obj: Record<string, SpecValue>): SpecValue {
  // capacity is present when Wh, or V+Ah (computable), is available
  if (col.key === "capacity_wh") {
    return _num(obj.capacity_wh) ?? (_num(obj.voltage_v) != null || _num(obj.amphours_ah) != null ? 1 : null);
  }
  // combined motor power present when either nominal or peak exists
  if (col.key === "motor_power") return _num(obj.power_w) ?? _num(obj.peak_w) ?? null;
  return obj[col.key] ?? null;
}

function isEmpty(v: SpecValue): boolean {
  // false counts as absent: the parsers always emit boolean flags (folding,
  // tubeless, lockout, ...) and false just means the spec never said so
  return v == null || v === "" || v === false || (Array.isArray(v) && v.length === 0);
}

export function renderCell(col: Column, obj: Record<string, SpecValue>, units: UnitSystem): string {
  if (col.key === "capacity_wh") return batteryCapacity(obj);
  if (col.key === "motor_power") return motorPower(obj);
  const v = rawValue(col, obj);
  if (isEmpty(v)) return "";
  if (typeof v === "boolean") return v ? "✓" : "";
  if (Array.isArray(v)) return v.map(String).join(", ");
  if (typeof v === "number") return formatNumber(v, 2, false) + (col.unit ?? "");
  if (typeof v !== "string") return formatSpecValue(v, units); // nested object fallback
  if (col.key === "details" || col.key === "__make") return formatSpecValue(v, units);
  // short enum-ish tokens ("hub", "continuously_variable") get prettified
  const pretty = /^[a-z][a-z_]*$/.test(v) ? titleCase(v) : v;
  return pretty + (col.unit ?? "");
}

/** A parsed component kind rendered as a feature-column table: column headers are
 *  the component's features, one value row per instance (Front / Rear / single).
 *  `emphasize` (used by the Ebike System card) bolds + indents the sub-category
 *  heading and the values beneath it. */
export function ComponentTable({
  kind,
  instances,
  emphasize = false,
}: {
  kind: string;
  instances: ComponentInstance[];
  emphasize?: boolean;
}) {
  const [units] = useUnits();
  const config = COLUMN_CONFIG[kind];
  if (!config || !instances.length) return null;
  // order positioned instances Front → Rear → Left → Right (size-labelled
  // instances keep their given order via the stable sort)
  const POS_RANK: Record<string, number> = { Front: 0, Rear: 1, Left: 2, Right: 3 };
  instances = [...instances].sort(
    (a, b) => (POS_RANK[a.position ?? ""] ?? 9) - (POS_RANK[b.position ?? ""] ?? 9),
  );
  // keep only columns that carry a value on at least one instance
  const present = config.filter((col) => instances.some((inst) => !isEmpty(rawValue(col, inst.obj))));
  if (!present.length) return null;
  // Make (manufacturer) + Model lead the table, then the feature columns
  const cols = [
    ...present.filter((col) => col.header === "Make"),
    ...present.filter((col) => col.header === "Model"),
    ...present.filter((col) => col.header !== "Make" && col.header !== "Model"),
  ];
  const showPos = instances.length > 1; // front/rear -> a value column per instance
  return (
    <div className="mb-3">
      <h3
        className={`mb-1 text-xs uppercase tracking-wide text-slate-500 ${
          emphasize ? "pl-2 font-bold" : "font-semibold"
        }`}
      >
        {KIND_LABEL[kind] ?? titleCase(kind)}
      </h3>
      <table className="w-full text-sm">
        {showPos && (
          <thead>
            <tr className="text-left text-xs font-medium text-slate-400">
              <th className="w-2/5 py-1 pr-3" />
              {instances.map((inst, i) => (
                <th key={i} className="py-1 pr-3">{inst.position ?? ""}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody className="divide-y divide-slate-100">
          {cols.map((col) => (
            <tr key={col.key} className="align-top">
              <th
                className={`w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500 ${
                  emphasize ? "pl-4" : ""
                }`}
              >
                {col.header}
              </th>
              {instances.map((inst, i) => (
                <td
                  key={i}
                  className={`py-1.5 pr-3 text-slate-800 ${emphasize ? "font-semibold" : ""}`}
                >
                  {renderCell(col, inst.obj, units)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
