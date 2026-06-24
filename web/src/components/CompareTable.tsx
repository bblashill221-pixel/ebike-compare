import type { Model, SpecValue } from "../types";
import { fieldLabel, formatSpecValue, titleCase, withUnit, hiddenUnitKeys } from "../format";
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

const GROUP_LABEL: Record<string, string> = { ebike_system: "eBike System" };

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

function groupRows(models: Model[], group: string, units: UnitSystem): Row[] {
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
  // components first, broken into their canonical fields (like the detail page)
  for (const kind of [...kinds].sort((a, b) => (KIND_RANK[a] ?? 99) - (KIND_RANK[b] ?? 99))) {
    if (foldPA && kind === "pedal_assist") continue;     // rendered under Motor below
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
    // append pedal-assist (Assist Modes / Boost) as Motor rows
    if (kind === "motor" && foldPA) {
      const pa = models.map((m) => mergeKind(m, group, "pedal_assist"));
      const paCols: [string, string][] = [["levels", "Assist Modes"], ["boost", "Boost"]];
      for (const [key, label] of paCols) {
        const col = { key, header: label };
        const values = pa.map((o) => (o ? renderCell(col, o, units) : "—"));
        if (values.some((v) => !isEmptyCell(v))) sub.push({ label, values, indent: true });
      }
    }
    if (sub.length) {
      rows.push({ label: KIND_LABEL[kind] ?? titleCase(kind), values: [], section: true });
      rows.push(...sub);
    }
  }
  // then plain scalar rows (paired off-unit rows hidden)
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
      <div>
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

export function CompareTable({ models }: { models: Model[] }) {
  const [units] = useUnits();
  const cols = `minmax(8rem,12rem) repeat(${models.length}, minmax(0,1fr))`;
  return (
    <div className="space-y-6">
      {GROUP_ORDER.filter((g) => models.some((m) => m.specs?.[g] && Object.keys(m.specs[g]).length)).map(
        (group) => (
          <div key={group} className="space-y-6">
            <Card title={GROUP_LABEL[group] ?? titleCase(group)} rows={groupRows(models, group, units)} cols={cols} models={models} />
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
