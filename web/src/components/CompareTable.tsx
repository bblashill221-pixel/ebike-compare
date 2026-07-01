import type { Model, SpecValue } from "../types";
import { fieldLabel, formatSpecValue, titleCase, groupLabel, withUnit, hiddenUnitKeys } from "../format";
import { useUnits, type UnitSystem } from "../units";
import { COLUMN_CONFIG, KIND_LABEL } from "./componentColumns";
import { renderCell } from "./ComponentTable";

// Spec groups shown in the detailed comparison, in order. "general_info" is dropped
// (it duplicates the key-specs table up top); its certifications + the warranty are
// surfaced in the synthetic "Safety and Support" section instead.
const GROUP_ORDER = [
  "ebike_system",
  "water_resistance",
  "frameset",
  "wheelset",
  "brakes",
  "drivetrain",
  "cockpit",
  "geometry",
  "included_accessories",
];

// canonical kind order within a group (the order KIND_LABEL is declared in)
const KIND_RANK: Record<string, number> = Object.fromEntries(
  Object.keys(KIND_LABEL).map((k, i) => [k, i]),
);

type SpecObj = Record<string, SpecValue>;
const isComponent = (v: SpecValue | undefined): v is SpecObj =>
  !!v && typeof v === "object" && !Array.isArray(v) && typeof (v as SpecObj)._kind === "string"
  && (v as SpecObj)._kind !== "cert";
const isCert = (v: SpecValue | undefined): v is SpecObj =>
  !!v && typeof v === "object" && !Array.isArray(v) && (v as SpecObj)._kind === "cert";

const isEmptyCell = (v: string) => v === "" || v === "—";

/** Merge a model's same-kind component instances in one group (front+rear, etc.) into
 *  one object: first non-empty value per field. */
function mergeKind(model: Model, group: string, kind: string): SpecObj | null {
  let out: SpecObj | null = null;
  for (const v of Object.values(model.specs?.[group] ?? {})) {
    if (isComponent(v) && v._kind === kind) {
      if (!out) out = {};
      for (const [k, val] of Object.entries(v)) {
        if ((out[k] == null || out[k] === "") && val != null && val !== "") out[k] = val;
      }
    }
  }
  return out;
}

type Row = { label: string; values: string[]; section?: boolean; indent?: boolean };

// Canonical geometry attribute key: strip the leading diagram number ("6_chain_stay…")
// and fold naming variants so the SAME measurement aligns into one compare row across
// bikes (and de-dups a bike that lists each attribute twice — numbered + plain).
function canonGeo(k: string): string {
  let c = k.toLowerCase().replace(/^\d+[_\s]+/, "");
  c = c.replace(/chain[_\s]?stay/, "chainstay").replace(/step[_\s]?over/, "standover")
       .replace(/_min$/, "_minimum").replace(/_max$/, "_maximum");
  if (c === "effective_top_tube") c = "effective_top_tube_length";
  return c;
}

function geometryRowsCompare(models: Model[], units: UnitSystem): Row[] {
  const order: string[] = [];
  const seen = new Set<string>();
  for (const m of models) {
    for (const k of Object.keys(m.specs?.geometry ?? {})) {
      const c = canonGeo(k);
      if (!seen.has(c)) { seen.add(c); order.push(c); }
    }
  }
  const rows: Row[] = [];
  for (const c of order) {
    const { label, unit } = fieldLabel(c);
    const values = models.map((m) => {
      for (const [k, v] of Object.entries(m.specs?.geometry ?? {})) {
        if (canonGeo(k) === c && v != null && v !== "" && !(Array.isArray(v) && v.length === 0))
          return withUnit(formatSpecValue(v, units), unit);
      }
      return "—";
    });
    if (values.some((v) => !isEmptyCell(v))) rows.push({ label, values });
  }
  return rows;
}

function groupRows(models: Model[], group: string, units: UnitSystem): Row[] {
  // Geometry has no parsed components — align its attributes by canonical name so the
  // same measurement is ONE row across bikes (and per-bike duplicates collapse).
  if (group === "geometry") return geometryRowsCompare(models, units);
  // discover component kinds + scalar field keys present across the models
  const kinds = new Set<string>();
  const scalarKeys: string[] = [];
  for (const m of models) {
    for (const [f, v] of Object.entries(m.specs?.[group] ?? {})) {
      if (isComponent(v)) kinds.add(v._kind as string);
      else if (!isCert(v) && !scalarKeys.includes(f)) scalarKeys.push(f);
    }
  }
  const rows: Row[] = [];
  // Pedal-assist is folded INTO the Motor section (it's a motor/system attribute), not
  // shown as its own block — when a motor is present in this group.
  const foldPA = kinds.has("motor") && kinds.has("pedal_assist");
  // The pedal-assist SENSOR (torque/cadence) folds into Motor as "Assist type".
  const foldSensor = kinds.has("motor") && kinds.has("sensor");
  // First non-empty scalar field in this group whose key matches rx (used to re-home a
  // loose eBike-System value under its component header, e.g. charging time -> Charger).
  const scalarMatch = (m: Model, rx: RegExp): SpecValue | undefined => {
    for (const [k, v] of Object.entries(m.specs?.[group] ?? {})) {
      if (!isComponent(v) && rx.test(k) && v != null && v !== ""
          && !(Array.isArray(v) && v.length === 0)) return v;
    }
    return undefined;
  };
  // components first, broken into their canonical fields (like the detail page)
  for (const kind of [...kinds].sort((a, b) => (KIND_RANK[a] ?? 99) - (KIND_RANK[b] ?? 99))) {
    if (foldPA && kind === "pedal_assist") continue;     // rendered under Motor below
    if (foldSensor && kind === "sensor") continue;       // assist type rendered under Motor
    const merged = models.map((m) => mergeKind(m, group, kind));
    // Model always leads, then Make, then the kind's feature columns (config order).
    const colRank = (key: string) => (key === "model" ? 0 : key === "manufacturer" ? 1 : 2);
    const cfg = COLUMN_CONFIG[kind]
      ? [...COLUMN_CONFIG[kind]].sort((a, b) => colRank(a.key) - colRank(b.key))
      : undefined;
    const sub: Row[] = [];
    if (cfg) {
      for (const col of cfg) {
        const values = merged.map((o) => (o ? renderCell(col, o, units) : "—"));
        if (values.some((v) => !isEmptyCell(v))) sub.push({ label: col.header, values, indent: true });
      }
    } else {
      const values = merged.map((o) => (o ? formatSpecValue(o, units) : "—"));
      if (values.some((v) => !isEmptyCell(v))) sub.push({ label: "Spec", values, indent: true });
    }
    // Assist type / levels / boost belong under Motor (folded from the pedal-assist
    // sensor + pedal_assist components), not shown as their own sections.
    if (kind === "motor") {
      const typeVals = models.map((m) => {
        const s = mergeKind(m, group, "sensor");
        if (s) {
          const r = renderCell({ key: "type", header: "Assist type" }, s, units);
          if (!isEmptyCell(r)) return r;
        }
        const v = scalarMatch(m, /^(pedal_?assist_type|assist_type|sensor_type)$/i);
        return v != null ? String(formatSpecValue(v, units)) : "—";
      });
      if (typeVals.some((v) => !isEmptyCell(v))) sub.push({ label: "Assist type", values: typeVals, indent: true });
      const magnetVals = models.map((m) => {
        const s = mergeKind(m, group, "sensor");
        return s ? renderCell({ key: "magnets", header: "Magnets" }, s, units) : "—";
      });
      if (magnetVals.some((v) => !isEmptyCell(v))) sub.push({ label: "Magnets", values: magnetVals, indent: true });
      const modeVals = models.map((m) => {
        const pa = mergeKind(m, group, "pedal_assist");
        if (pa) {
          const r = renderCell({ key: "levels", header: "Assist levels" }, pa, units);
          if (!isEmptyCell(r)) return r;
        }
        const v = scalarMatch(m, /^(pedal_?assist_(modes|levels|type)|assist_(modes|levels))$/i);
        return v != null ? String(formatSpecValue(v, units)) : "—";
      });
      if (modeVals.some((v) => !isEmptyCell(v))) sub.push({ label: "Assist levels", values: modeVals, indent: true });
      const boostVals = models.map((m) => {
        const pa = mergeKind(m, group, "pedal_assist");
        return pa ? renderCell({ key: "boost", header: "Boost" }, pa, units) : "—";
      });
      if (boostVals.some((v) => !isEmptyCell(v))) sub.push({ label: "Boost", values: boostVals, indent: true });
    }
    // Charging time belongs under the Charger (it's a loose eBike-System scalar).
    if (kind === "charger") {
      const ctVals = models.map((m) => {
        const v = scalarMatch(m, /^(charging_time|charge_time|recharging_time|duration_of_charging)/i);
        return v != null ? String(formatSpecValue(v, units)) : "—";
      });
      if (ctVals.some((v) => !isEmptyCell(v))) sub.push({ label: "Charge Time", values: ctVals, indent: true });
    }
    if (sub.length) {
      rows.push({ label: KIND_LABEL[kind] ?? titleCase(kind), values: [], section: true });
      rows.push(...sub);
    }
  }
  // Plain scalar rows. SKIPPED for eBike System: every loose value there is either a
  // duplicate of the key-specs table up top (torque, top speed, power, weight) or
  // belongs under a component header (charging time -> Charger, cells -> Battery), plus
  // a long tail of marketing junk -- so the group shows only its component breakdowns.
  if (group !== "ebike_system") {
    const hide = hiddenUnitKeys(scalarKeys, units);
    for (const f of scalarKeys) {
      if (hide.has(f)) continue;
      const { label, unit } = fieldLabel(f);
      const values = models.map((m) => {
        const v = m.specs?.[group]?.[f] as SpecValue | undefined;
        if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) return "—";
        return withUnit(formatSpecValue(v, units), unit);
      });
      if (values.some((v) => !isEmptyCell(v))) rows.push({ label, values });
    }
  }
  return rows;
}

/** Certifications (anywhere in specs) + warranty — the unique General-Info values. */
function safetyRows(models: Model[]): Row[] {
  const certFields: string[] = [];
  for (const m of models) {
    for (const fields of Object.values(m.specs ?? {})) {
      for (const [f, v] of Object.entries(fields ?? {})) {
        if (isCert(v) && !certFields.includes(f)) certFields.push(f);
      }
    }
  }
  const certLabel = (f: string) =>
    f === "safety_certifications" ? "eBike Safety Certifications" : fieldLabel(f).label;
  const rows: Row[] = [];
  for (const f of certFields) {
    const values = models.map((m) => {
      for (const fields of Object.values(m.specs ?? {})) {
        const v = (fields ?? {})[f] as SpecValue | undefined;
        if (isCert(v)) {
          const std = (v as SpecObj).standards;
          return Array.isArray(std) && std.length ? std.map(String).join(", ") : "—";
        }
      }
      return "—";
    });
    if (values.some((v) => !isEmptyCell(v))) rows.push({ label: certLabel(f), values });
  }
  const warranty = models.map((m) => m.warranty || "—");
  if (warranty.some((v) => !isEmptyCell(v))) rows.push({ label: "Warranty", values: warranty });
  return rows;
}

function Card({ title, rows, cols, models }: { title: string; rows: Row[]; cols: string; models: Model[] }) {
  if (!rows.length) return null;
  return (
    <div className="card overflow-hidden">
      <h3 className="border-b border-slate-100 bg-slate-50 px-4 py-2 font-semibold text-slate-800">{title}</h3>
      {/* desktop: eBikes as columns */}
      <div className="hidden md:block">
        {/* model-name header row (same as the Metrics card) */}
        <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
          <div className="px-4 py-2" />
          {models.map((m) => (
            <div key={m.id} className="truncate border-l border-slate-100 px-4 py-2 text-xs font-bold text-slate-800">{m.model}</div>
          ))}
        </div>
        {rows.map((row, idx) =>
          row.section ? (
            <div key={`s${idx}`} className="border-b border-slate-100 bg-slate-50/70 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-slate-700">
              {row.label}
            </div>
          ) : (
            <RowLine key={`${row.label}-${idx}`} row={row} cols={cols} />
          ),
        )}
      </div>
      {/* mobile: inverted — each field lists a line per eBike (name — value) */}
      <div className="md:hidden">
        {rows.map((row, idx) =>
          row.section ? (
            <div key={`ms${idx}`} className="border-b border-slate-100 bg-slate-50/70 px-4 py-1.5 text-xs font-bold uppercase tracking-wide text-slate-700">
              {row.label}
            </div>
          ) : (
            <MobileRow key={`m-${row.label}-${idx}`} row={row} models={models} />
          ),
        )}
      </div>
    </div>
  );
}

function RowLine({ row, cols }: { row: Row; cols: string }) {
  const differ = new Set(row.values.filter((v) => !isEmptyCell(v))).size > 1;
  return (
    <div className="grid border-b border-slate-50 last:border-0" style={{ gridTemplateColumns: cols }}>
      <div className={`bg-slate-50/50 px-4 py-2 text-sm font-medium text-slate-500 ${row.indent ? "pl-8" : ""}`}>{row.label}</div>
      {row.values.map((v, i) => (
        <div key={i} className={`border-l border-slate-100 px-4 py-2 text-sm text-slate-800 ${differ ? "bg-amber-50/60" : ""}`}>
          {v}
        </div>
      ))}
    </div>
  );
}

// Mobile: one field = its label + a line per eBike (name — value). Amber tint when values differ.
function MobileRow({ row, models }: { row: Row; models: Model[] }) {
  const differ = new Set(row.values.filter((v) => !isEmptyCell(v))).size > 1;
  return (
    <div className={`border-b border-slate-100 px-4 py-2 last:border-0 ${row.indent ? "pl-6" : ""}`}>
      <div className="text-sm font-medium text-slate-500">{row.label}</div>
      <div className={`mt-1 space-y-0.5 rounded ${differ ? "bg-amber-50/60 px-2 py-1" : ""}`}>
        {models.map((m, i) => (
          <div key={m.id} className="flex items-start justify-between gap-2 text-sm">
            <span className="min-w-0 flex-1 text-xs font-medium uppercase leading-tight tracking-wide text-slate-400">{m.model}</span>
            <span className="min-w-0 max-w-[52%] shrink-0 break-words text-right font-medium leading-tight text-slate-800">{row.values[i]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function CompareTable({ models }: { models: Model[] }) {
  const [units] = useUnits();
  const cols = `minmax(8rem,12rem) repeat(${models.length}, minmax(0,1fr))`;
  return (
    <div className="space-y-6">
      {GROUP_ORDER.filter((g) => models.some((m) => m.specs?.[g] && Object.keys(m.specs[g]).length)).map(
        (group) => (
          <div key={group} className="space-y-6">
            <Card title={groupLabel(group)} rows={groupRows(models, group, units)} cols={cols} models={models} />
            {/* Safety & Support sits right after eBike System */}
            {group === "ebike_system" && (
              <Card title="Safety and Support" rows={safetyRows(models)} cols={cols} models={models} />
            )}
          </div>
        ),
      )}
    </div>
  );
}
