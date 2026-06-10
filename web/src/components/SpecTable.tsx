import type { SpecGroup, SpecValue } from "../types";
import { formatSpecValue, hiddenUnitKeys, labelize, titleCase } from "../format";
import { useUnits } from "../units";
import { ComponentTable, type ComponentInstance } from "./ComponentTable";
import { COLUMN_CONFIG } from "./componentColumns";

function isEmpty(v: SpecValue): boolean {
  if (v == null || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") return Object.keys(v).length === 0;
  return false;
}

/** A spec value that's a parsed component (object with a configured _kind). */
function asComponent(v: SpecValue): Record<string, SpecValue> | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const obj = v as Record<string, SpecValue>;
    const kind = obj._kind;
    if (typeof kind === "string" && COLUMN_CONFIG[kind]) return obj;
  }
  return null;
}

/** Front/Rear/Left/Right instance label from a field key, else null (single). */
function positionOf(key: string): string | null {
  const m = key.match(/^(front|rear|left|right)_/);
  return m ? titleCase(m[1]) : null;
}

export function SpecTable({ group }: { group: SpecGroup }) {
  const [units] = useUnits();
  const entries = Object.entries(group).filter(([, v]) => !isEmpty(v));

  // bucket parsed components by _kind (front+rear -> two rows; multiple labels
  // of one kind at the same position -> merged, first non-empty value wins).
  const order: string[] = [];
  const buckets: Record<string, ComponentInstance[]> = {};
  const scalarKeys: string[] = [];
  for (const [k, v] of entries) {
    const comp = asComponent(v);
    if (!comp) {
      scalarKeys.push(k);
      continue;
    }
    const kind = comp._kind as string;
    if (!buckets[kind]) {
      buckets[kind] = [];
      order.push(kind);
    }
    const pos = positionOf(k);
    const existing = buckets[kind].find((inst) => inst.position === pos);
    if (existing) {
      for (const [kk, vv] of Object.entries(comp)) {
        if (existing.obj[kk] == null || existing.obj[kk] === "") existing.obj[kk] = vv;
      }
    } else {
      buckets[kind].push({ position: pos, obj: { ...comp } });
    }
  }

  // remaining scalars render in the simple label/value table (unit-deduped)
  const hide = hiddenUnitKeys(scalarKeys, units);
  const scalarRows = scalarKeys.filter((k) => !hide.has(k));

  if (!order.length && !scalarRows.length) return null;

  return (
    <div>
      {order.map((kind) => (
        <ComponentTable key={kind} kind={kind} instances={buckets[kind]} />
      ))}
      {scalarRows.length > 0 && (
        <table className="w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {scalarRows.map((k) => (
              <tr key={k} className="align-top">
                <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">
                  {labelize(k)}
                </th>
                <td className="py-1.5 text-slate-800">{formatSpecValue(group[k], units)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
