import { Fragment, type ReactNode } from "react";
import type { SpecGroup, SpecValue } from "../types";
import { fieldLabel, formatSpecValue, hiddenUnitKeys, titleCase, withUnit } from "../format";
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

/** Front/Rear/Left/Right instance label from a field key, else null (single).
 *  Light keys also use head-/tail- (headlight → Front, tail_light → Rear). */
const _POSITION: Record<string, string> = {
  front: "Front", rear: "Rear", left: "Left", right: "Right",
  tail: "Rear", head: "Front",
};
function positionOf(key: string): string | null {
  const m = key.match(/^(front|rear|left|right|tail|head)(?:_|light\b|$)/);
  return m ? (_POSITION[m[1]] ?? titleCase(m[1])) : null;
}

/** Expand a parsed component into one instance per column. A `by_size` map (e.g.
 *  handlebar width/rise that differ by frame size) becomes a column per size,
 *  with the shared attributes repeated in each; otherwise it's a single instance
 *  positioned by its field key (front/rear/…). */
function expandComponent(key: string, comp: Record<string, SpecValue>): ComponentInstance[] {
  const { by_size, ...common } = comp;
  if (by_size && typeof by_size === "object" && !Array.isArray(by_size)) {
    const sizes = by_size as Record<string, Record<string, SpecValue>>;
    const labels = Object.keys(sizes);
    if (labels.length) {
      return labels.map((label) => ({ position: label, obj: { ...common, ...sizes[label] } }));
    }
  }
  return [{ position: positionOf(key), obj: { ...common } }];
}

// Canonical render order for component kinds, so every card lists them the same
// way regardless of scrape order (Ebike System: motor → battery → charger →
// controller → display → sensor → pedal assist → throttle, then the rest).
const KIND_ORDER = [
  "motor", "battery", "charger", "controller", "display", "sensor", "pedal_assist", "throttle",
  "frame", "fork", "shock",
  "derailleur", "cassette", "chain", "chainring", "crankset", "bottom_bracket", "pedals",
  "brake",
  "wheel", "tire", "rims", "spokes", "tubes",
  "handlebars", "stem", "seatpost", "saddle", "grips", "seat_binder",
  "light", "cert",
];
const kindRank = (k: string) => {
  const i = KIND_ORDER.indexOf(k);
  return i < 0 ? KIND_ORDER.length : i;
};

// Scalar spec keys that just restate a typed fact shown elsewhere (top tiles /
// Speed): suppressed from the main spec cards so a value isn't repeated by itself.
const CAPTURED_SCALAR = (k: string): boolean =>
  /^(max|top)_speed_(mph|kph)$/.test(k) ||
  /^motor_?(power_)?w$/.test(k) ||
  /^(motor_)?peak_?(power_)?w$/.test(k) ||
  /^torque_nm$/.test(k) ||
  /^battery_(capacity_)?wh$/.test(k) ||
  /^range_(mi|km)$/.test(k) ||
  /^(net_)?weight_(lb|kg)$/.test(k);

export function SpecTable({
  group,
  emphasize = false,
  subRows,
  hideCaptured = false,
}: {
  group: SpecGroup;
  emphasize?: boolean;
  // extra content rendered indented directly beneath the row with this field key
  subRows?: Record<string, ReactNode>;
  // drop standalone scalar rows that merely restate a typed fact (tiles/Speed)
  hideCaptured?: boolean;
}) {
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
    for (const variant of expandComponent(k, comp)) {
      const existing = buckets[kind].find((inst) => inst.position === variant.position);
      if (existing) {
        for (const [kk, vv] of Object.entries(variant.obj)) {
          if (existing.obj[kk] == null || existing.obj[kk] === "") existing.obj[kk] = vv;
        }
      } else {
        buckets[kind].push(variant);
      }
    }
  }

  // When a kind has both positioned (Front/Rear/…) and unpositioned instances,
  // fold the unpositioned ones into the first positioned instance instead of
  // rendering a confusing unlabeled column beside it. e.g. a "shifter" row routed
  // to the derailleur kind merges into the Rear derailleur (which keeps its model).
  for (const kind of order) {
    const insts = buckets[kind];
    const positioned = insts.filter((i) => i.position);
    if (positioned.length && positioned.length < insts.length) {
      const main = positioned[0];
      for (const inst of insts) {
        if (inst.position) continue;
        for (const [kk, vv] of Object.entries(inst.obj)) {
          if (main.obj[kk] == null || main.obj[kk] === "") main.obj[kk] = vv;
        }
      }
      buckets[kind] = positioned;
    }
  }

  // canonical component order (consistent across bikes, not scrape order)
  order.sort((a, b) => kindRank(a) - kindRank(b));
  // certifications render at the very BOTTOM of the section (below the scalar
  // rows), not in the component block — they were relocated into Key Aspects.
  const certKinds = order.filter((k) => k === "cert");
  const mainKinds = order.filter((k) => k !== "cert");

  // remaining scalars render in the simple label/value table (unit-deduped);
  // optionally drop ones already captured as a typed fact (tiles/Speed)
  const hide = hiddenUnitKeys(scalarKeys, units);
  const scalarRows = scalarKeys.filter(
    (k) => !hide.has(k) && !(hideCaptured && CAPTURED_SCALAR(k)),
  );

  if (!mainKinds.length && !scalarRows.length && !certKinds.length) return null;

  return (
    <div>
      {mainKinds.map((kind) => (
        <ComponentTable key={kind} kind={kind} instances={buckets[kind]} emphasize={emphasize} />
      ))}
      {scalarRows.length > 0 && (
        <table className="w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {scalarRows.map((k) => {
              const { label, unit } = fieldLabel(k);
              const sub = subRows?.[k];
              return (
                <Fragment key={k}>
                  <tr className="align-top">
                    <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">
                      {label}
                    </th>
                    <td className="py-1.5 text-slate-800">
                      {withUnit(formatSpecValue(group[k], units), unit)}
                    </td>
                  </tr>
                  {sub && (
                    <tr className="border-t-0 align-top">
                      <td colSpan={2} className="pb-1.5 pl-4 text-xs text-slate-500">
                        {sub}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
      {certKinds.map((kind) => (
        <ComponentTable key={kind} kind={kind} instances={buckets[kind]} emphasize={emphasize} />
      ))}
    </div>
  );
}
