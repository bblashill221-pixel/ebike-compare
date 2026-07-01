import React from "react";
import type { Model } from "../types";
import { isAvailable } from "../soldOut";
import { formatNumber, titleCase } from "../format";
import { displayName } from "./BikeCard";
import { BatteryIcon, BoltIcon, MotorIcon, PayloadIcon, RangeIcon, TagIcon, TorqueIcon, WeightIcon } from "./icons";
import type { UnitSystem } from "../units";

// Uppercase but keep the lowercase-e type names intact (eMTB, eMoto) — used for headers
// that embed the product type so CSS `uppercase` doesn't turn "eMTB" into "EMTB".
const upEmtb = (s: string) => s.toUpperCase().replace(/EMTB/g, "eMTB").replace(/EMOTO/g, "eMoto");

// Rank bolts: a lightning-bolt COUNT bucketed by the bike's percentile (rank / total), 1 = top.
// ≤10% → 4 bolts, ≤20% → 3, ≤30% → 2, ≤40% → 1, else → none. Amber, like the logo bolt.
function rankBoltCount(p: number): number {
  if (p <= 0.1) return 4;
  if (p <= 0.2) return 3;
  if (p <= 0.3) return 2;
  if (p <= 0.4) return 1;
  return 0;
}
// A single bolt with the rating number (1–4) overlaid on it. `dense` = a smaller, less-overhanging
// number circle for tight tables (Compare page) so the badge barely exceeds the bolt's footprint.
export function BoltBadge({ n, className = "h-5 w-5", dense = false }: { n: number; className?: string; dense?: boolean }) {
  return (
    <span className="relative inline-flex shrink-0 items-center justify-center text-amber-500">
      <BoltIcon className={className} />
      {/* number sits in a circle at the corner so the bolt stays fully visible */}
      <span className={`absolute flex items-center justify-center rounded-full bg-white font-bold leading-none text-slate-900 shadow ring-1 ring-amber-500 ${dense ? "-bottom-0.5 -right-0.5 h-3 w-3 text-[8px]" : "-bottom-1 -right-1 h-[15px] w-[15px] text-[10px]"}`}>
        {n}
      </span>
    </span>
  );
}
// Detail page: the original N separate bolts (1–4, no number).
export function RankBolts({ rank, total, boltClass = "h-5 w-5" }: { rank: number; total: number; boltClass?: string }) {
  if (total <= 0) return null;
  const p = Math.max(0, Math.min(1, rank / total));
  const n = rankBoltCount(p);
  if (n === 0) return null;
  return (
    <span className="inline-flex items-center gap-0.5 text-amber-500" title={`Top ${Math.round(p * 100)}% — rank ${rank} of ${total}`}>
      {Array.from({ length: n }, (_, i) => <BoltIcon key={i} className={boltClass} />)}
    </span>
  );
}
// Compare page: a single bolt with the rating number in a corner circle.
export function RankBadge({ rank, total, boltClass = "h-5 w-5", dense = false }: { rank: number; total: number; boltClass?: string; dense?: boolean }) {
  if (total <= 0) return null;
  const p = Math.max(0, Math.min(1, rank / total));
  const n = rankBoltCount(p);
  if (n === 0) return null;
  return (
    <span className="inline-flex" title={`Top ${Math.round(p * 100)}% — rank ${rank} of ${total}`}>
      <BoltBadge n={n} className={boltClass} dense={dense} />
    </span>
  );
}

// (icons are self-colored: battery emerald, motor amber, torque rose, range sky, weight violet,
// price tag blue). `score` maps to the within-type dimension-score key; metrics without one omit it.
export const PERCENTILE_FIELDS: {
  field: string;
  label: string;
  unit?: string;
  icon: React.ReactNode;
  badge: string;
  lowerBetter?: boolean;   // LOWER is better -> below median is the "good" (green) direction
  score?: string;
}[] = [
  { field: "price", label: "Price", unit: "$", icon: <TagIcon className="h-4 w-4" />, badge: "bg-blue-50", lowerBetter: true, score: "price" },
  { field: "battery_wh", label: "Battery", unit: " Wh", icon: <BatteryIcon className="h-4 w-4" />, badge: "bg-emerald-50", score: "battery" },
  { field: "motor_w", label: "Motor (Nominal)", unit: " W", icon: <MotorIcon className="h-4 w-4" />, badge: "bg-amber-50", score: "power" },
  { field: "motor_peak_w", label: "Motor (Peak)", unit: " W", icon: <MotorIcon className="h-4 w-4" />, badge: "bg-amber-50" },
  { field: "torque_nm", label: "Torque", unit: " Nm", icon: <TorqueIcon className="h-4 w-4" />, badge: "bg-rose-50", score: "torque" },
  { field: "range_mi", label: "Range", unit: " mi", icon: <RangeIcon className="h-4 w-4" />, badge: "bg-sky-50", score: "range" },
  { field: "weight_lb", label: "Weight", unit: " lb", icon: <WeightIcon className="h-4 w-4" />, badge: "bg-violet-50", lowerBetter: true, score: "weight" },
  { field: "max_load_lb", label: "Payload", unit: " lb", icon: <PayloadIcon className="h-4 w-4" />, badge: "bg-teal-50" },
];

interface Props {
  model: Model;
  /** all models — the in-stock same-type cohort is computed from these */
  models: Model[];
  units: UnitSystem;
  /** show the Low (Min) / High (Max) columns. Hidden on the Compare page for space. */
  showExtremes?: boolean;
  /** header over the bike's own value column (e.g. "This eBike"); defaults to the model name. */
  valueLabel?: string;
  /** tighter padding + shortened headers (Compare page). */
  compact?: boolean;
  /** even smaller + body grid lines — the miniature stacked side-by-side form on Compare. */
  mini?: boolean;
}

// The "How It Compares" table: one bike's metrics vs its IN-STOCK same-type cohort
// (Low / Median / High, the bike's value, difference vs median, and a rank). Sold-out bikes
// are excluded so rank + stats match Browse. Shared by the detail page and the Compare page.
export function HowItCompares({ model, models, units, showExtremes = true, valueLabel, compact = false, mini = false }: Props) {
  const primaryType = model.analysis?.primary_type;
  const compareCohort = models.filter((m) =>
    (primaryType ? m.analysis?.primary_type === primaryType : true) && isAvailable(m));
  const valForModel = (m: Model, field: string): number | undefined =>
    field === "price" ? (m.price ?? m.price_min ?? undefined)
                      : (m.analysis?.specs_typed?.[field] as number | undefined);
  const valueOf = (field: string) =>
    field === "price" ? (model.price ?? model.price_min)
                      : (model.analysis?.specs_typed?.[field] as number | undefined);

  const cohortStats: Record<string, { min: number; p50: number; max: number; count: number }> = {};
  const extremes: Record<string, { lo?: Model; hi?: Model }> = {};
  for (const { field } of PERCENTILE_FIELDS) {
    let lo: Model | undefined, hi: Model | undefined, loV = Infinity, hiV = -Infinity;
    const vals: number[] = [];
    for (const m of compareCohort) {
      const x = valForModel(m, field);
      if (typeof x !== "number") continue;
      vals.push(x);
      if (x < loV) { loV = x; lo = m; }
      if (x > hiV) { hiV = x; hi = m; }
    }
    extremes[field] = { lo, hi };
    if (vals.length) {
      vals.sort((a, b) => a - b);
      const mid = Math.floor(vals.length / 2);
      const p50 = vals.length % 2 ? vals[mid] : (vals[mid - 1] + vals[mid]) / 2;
      cohortStats[field] = { min: vals[0], max: vals[vals.length - 1], p50, count: vals.length };
    }
  }

  // density + label knobs (mini = the smaller, grid-lined Compare-page miniature)
  const cPad = mini ? "px-1.5 py-1" : compact ? "px-1.5 py-1.5" : "px-2 py-3";
  const hPad = mini ? "px-1.5 py-0.5" : compact ? "px-1.5 py-1" : "px-2 py-2";
  const iconSz = mini ? "h-5 w-5" : compact ? "h-6 w-6" : "h-9 w-9";
  const valPad = mini ? "px-1.5 py-0.5" : compact ? "px-2 py-0.5" : "px-3 py-1";
  const boltSz = mini ? "h-3.5 w-3.5" : compact ? "h-4 w-4" : "h-5 w-5";
  const tA = "text-center";   // values centered (matches the design template)
  const valueHeader = valueLabel ?? model.model;
  // Slanted parallelogram column header (horizontal text) per the design template. `highlight`
  // = the bike's own column (blue outline + tint); `caret` = the small ▾ under Low/Median/High.
  const ph = (label: React.ReactNode, opts: { caret?: boolean; highlight?: boolean; span?: number; noUpper?: boolean } = {}) => (
    <th colSpan={opts.span} className="relative p-0 align-bottom">
      <div className={`pointer-events-none absolute inset-0 -skew-x-[14deg] ${opts.highlight ? "rounded-t-md border-2 border-b-0 border-blue-500 bg-blue-50/70" : "border-l border-slate-200"}`} />
      <div className={`relative mx-auto max-w-[7.5rem] px-2 pb-2 pt-3 text-center ${mini ? "text-[10px]" : "text-[11px]"} font-bold ${opts.noUpper ? "" : "uppercase"} leading-tight ${opts.highlight ? "text-blue-700" : "text-slate-500"}`}>
        {label}
        {opts.caret && (
          <svg className="mx-auto mt-1 h-2 w-2 text-slate-400" viewBox="0 0 8 8" fill="currentColor" aria-hidden><path d="M1 2.5h6L4 6.5z" /></svg>
        )}
      </div>
    </th>
  );
  // Angled (diagonal) column header — rotates the label 45° so a narrow value column can still
  // carry a long header. Anchored at the column's bottom, contained within a tall header cell so
  // it never overflows the thead. Used on the Compare-page mini tables.
  const ah = (label: React.ReactNode, opts: { highlight?: boolean; span?: number } = {}) => (
    <th colSpan={opts.span} className="h-24 p-0 align-bottom">
      <div className="relative h-full">
        <span className={`absolute bottom-1 left-1/2 origin-bottom-left -rotate-45 whitespace-nowrap text-[10px] font-bold uppercase leading-none ${opts.highlight ? "text-blue-700" : "text-slate-500"}`}>
          {label}
        </span>
      </div>
    </th>
  );

  return (
    <div className="overflow-visible">
      <table className={`border-collapse ${mini ? "text-xs [&_tbody_td]:border [&_tbody_td]:border-slate-200/70" : "text-sm"}`}>
        <thead>
          <tr className="border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-slate-400">
            <th className={`${hPad} text-left align-bottom`}>Metric</th>
            {compact && mini ? (
              <>
                {showExtremes && ah("Low")}
                {ah("Median")}
                {showExtremes && ah("High")}
                {ah(valueHeader, { highlight: true })}
                {ah("Diff vs Median")}
                {ah("Rank Within Type", { span: 2 })}
              </>
            ) : compact ? (
              <>
                {showExtremes && ph("Low (Min)", { caret: true })}
                {ph("Median", { caret: true })}
                {showExtremes && ph("High (Max)", { caret: true })}
                {ph(valueHeader, { highlight: true })}
                {ph("Difference vs Median")}
                {ph(upEmtb(primaryType ? `Rank Among All ${primaryType} eBikes` : "Rank"), { span: 2, noUpper: true })}
              </>
            ) : (
              <>
                {showExtremes && <th className={`${hPad} text-center`}>Low (Min)</th>}
                <th className={`${hPad} text-center`}>Median</th>
                {showExtremes && <th className={`${hPad} text-center`}>High (Max)</th>}
                <th className={`${hPad} text-center ${valueLabel ? "" : "normal-case text-slate-600"}`}>{valueHeader}</th>
                <th className={`${hPad} text-center`}>Difference vs Median</th>
                <th className={`${hPad} text-center`} colSpan={2}>
                  {primaryType ? `Rank Among All ${primaryType} eBikes` : "Rank"}
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {PERCENTILE_FIELDS.map(({ field, label, unit, icon, badge, lowerBetter }) => {
            let stat = cohortStats[field];
            let v = valueOf(field);
            let u = unit;
            if (!stat) return null;
            if (units === "metric") {
              const conv = field === "range_mi" ? 1.60934
                : field === "weight_lb" || field === "max_load_lb" ? 0.453592 : null;
              if (conv) {
                const sc = (n: number) => n * conv;
                stat = { ...stat, min: sc(stat.min), p50: sc(stat.p50), max: sc(stat.max) };
                if (v != null) v = Math.round(sc(v));
                u = field === "range_mi" ? " km" : " kg";
              }
            }
            const fmt = (n: number) =>
              u === "$" ? `$${formatNumber(Math.round(n))}` : `${formatNumber(Math.round(n))}${u ?? ""}`;
            const diff = v == null ? null : Math.round(v - stat.p50);
            const better = diff != null && diff !== 0 && (lowerBetter ? diff < 0 : diff > 0);
            const worse = diff != null && diff !== 0 && !better;
            const diffStr =
              diff == null ? "—"
              : `${u === "$" ? `$${formatNumber(Math.abs(diff))}` : `${formatNumber(Math.abs(diff))}${u ?? ""}`}`;
            const myVal = valForModel(model, field);
            let rankStr: string | null = null;
            let rankN: number | null = null;
            let rankTotal = 0;
            if (myVal != null) {
              const vals = compareCohort
                .map((m) => valForModel(m, field))
                .filter((x): x is number => typeof x === "number");
              rankN = vals.filter((x) => (lowerBetter ? x < myVal : x > myVal)).length + 1;
              rankTotal = vals.length;
              rankStr = `${rankN} / ${rankTotal}`;
            }
            const ex = extremes[field];
            const bikeName = (m: Model) =>
              displayName(m).toLowerCase().includes(m.brand.toLowerCase())
                ? displayName(m)
                : `${titleCase(m.brand)} ${displayName(m)}`;
            return (
              <tr key={field} className="border-b border-slate-100 last:border-0">
                <td className={cPad}>
                  <div className={`flex items-center ${compact ? "gap-2" : "gap-3"}`}>
                    <span className={`flex ${iconSz} shrink-0 items-center justify-center rounded-full ${badge}`}>{icon}</span>
                    <div className="font-semibold text-slate-800">{label}</div>
                  </div>
                </td>
                {showExtremes && (
                  <td className={`${cPad} ${tA} text-slate-500`}>
                    <span className="group relative inline-block">
                      {fmt(stat.min)}
                      {ex?.lo && (
                        <span className="pointer-events-none absolute left-1/2 top-full z-50 hidden -translate-x-1/2 translate-y-1 whitespace-nowrap rounded bg-amber-100 px-2 py-1 text-xs font-medium text-slate-900 shadow-lg ring-1 ring-amber-300 group-hover:block">
                          {bikeName(ex.lo)}
                        </span>
                      )}
                    </span>
                  </td>
                )}
                <td className={`${cPad} ${tA} text-slate-500`}>{fmt(stat.p50)}</td>
                {showExtremes && (
                  <td className={`${cPad} ${tA} text-slate-500`}>
                    <span className="group relative inline-block">
                      {fmt(stat.max)}
                      {ex?.hi && (
                        <span className="pointer-events-none absolute left-1/2 top-full z-50 hidden -translate-x-1/2 translate-y-1 whitespace-nowrap rounded bg-amber-100 px-2 py-1 text-xs font-medium text-slate-900 shadow-lg ring-1 ring-amber-300 group-hover:block">
                          {bikeName(ex.hi)}
                        </span>
                      )}
                    </span>
                  </td>
                )}
                <td className={`${cPad} ${tA}`}>
                  <span className={`inline-block rounded-md ${valPad} font-bold text-slate-900 ${badge}`}>
                    {v == null ? "—" : fmt(v)}
                  </span>
                </td>
                <td className={`${cPad} ${tA}`}>
                  <span className={`inline-flex items-center gap-1 font-semibold ${better ? "text-emerald-600" : worse ? "text-rose-500" : "text-slate-400"}`}>
                    {diff != null && diff !== 0 && (
                      <svg className="h-2 w-2" viewBox="0 0 8 8" fill="currentColor" aria-hidden>
                        <path d={diff > 0 ? "M4 1l3 5H1z" : "M1 2h6l-3 5z"} />
                      </svg>
                    )}
                    {diffStr}
                  </span>
                </td>
                <td className={`${cPad} text-right tabular-nums text-slate-600`}>
                  {rankStr ?? <span className="text-slate-400">—</span>}
                </td>
                <td className={`${cPad} text-left`}>
                  {rankN != null && <RankBolts rank={rankN} total={rankTotal} boltClass={boltSz} />}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Compare-page combined table: metric field names listed ONCE down the left; each model is a
// column-GROUP of wrapped sub-column headers (Low·Median·High·This eBike·Diff·Rank, numbered-bolt
// rank). Tuned (dense bolt, tight padding) so 4 bikes fit a desktop container without scroll.
export function HowEachComparesTable({
  models, allModels, units,
}: { models: Model[]; allModels: Model[]; units: UnitSystem }) {
  // always show Low/High — there's room even at 4 bikes
  const subCols = [{ l: "Low" }, { l: "Median" }, { l: "High" }, { l: "This eBike", h: true }, { l: "Diff vs Median" }, { l: "Rank Within Type" }];
  const valForModel = (m: Model, field: string): number | undefined =>
    field === "price" ? (m.price ?? m.price_min ?? undefined)
                      : (m.analysis?.specs_typed?.[field] as number | undefined);
  const cohorts = models.map((s) => {
    const pt = s.analysis?.primary_type;
    return allModels.filter((m) => (pt ? m.analysis?.primary_type === pt : true) && isAvailable(m));
  });
  const cellCls = (groupStart: boolean) =>
    `px-0.5 py-1 text-center align-middle ${groupStart ? "border-l-2 border-slate-300" : "border-l border-slate-100"}`;
  return (
    <div className="overflow-visible">
      <table className="border-collapse text-[11px]">
        <thead>
          {/* model-name row: one header spanning each model's group of sub-columns */}
          <tr>
            <th className="border-b border-slate-200 p-1" />
            {models.map((m) => (
              <th key={m.id} colSpan={subCols.length} className="border-l-2 border-slate-300 px-1 pt-1 text-center align-bottom">
                <div className="text-[11px] font-bold leading-tight text-slate-800">{m.model}</div>
                <div className="text-[10px] font-semibold text-brand-600">{upEmtb(m.analysis?.primary_type ?? "")}</div>
              </th>
            ))}
          </tr>
          {/* sub-column headers (horizontal, wrapped to fit a narrow column), per model group */}
          <tr>
            <th className="border-b-2 border-slate-300 px-1 align-bottom text-left text-[10px] font-semibold uppercase tracking-wide text-slate-400">Metric</th>
            {models.map((_, gi) =>
              subCols.map((c, ci) => (
                <th key={`h-${gi}-${ci}`} className={`border-b-2 border-slate-300 px-0.5 pb-1 pt-2 align-bottom ${ci === 0 ? "border-l-2 border-slate-300" : "border-l border-slate-100"}`}>
                  <span className={`mx-auto block max-w-[2.75rem] text-center text-[9px] font-bold uppercase leading-tight ${c.h ? "text-blue-700" : "text-slate-500"}`}>
                    {c.l}
                  </span>
                </th>
              )),
            )}
          </tr>
        </thead>
        <tbody>
          {PERCENTILE_FIELDS.map(({ field, label, unit, icon, badge, lowerBetter }) => {
            if (!models.some((s) => valForModel(s, field) != null)) return null;
            return (
              <tr key={field} className="border-b border-slate-200 last:border-0">
                <td className="px-1 py-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full ${badge}`}>{icon}</span>
                    <span className="font-semibold text-slate-800">{label}</span>
                  </div>
                </td>
                {models.map((s, gi) => {
                  const rawVals = cohorts[gi].map((m) => valForModel(m, field)).filter((x): x is number => typeof x === "number");
                  const raw = valForModel(s, field);
                  if (raw == null || !rawVals.length) {
                    return subCols.map((_, ci) => <td key={`${gi}-${ci}`} className={`${cellCls(ci === 0)} text-slate-300`}>—</td>);
                  }
                  const sorted = [...rawVals].sort((a, b) => a - b);
                  const mid = Math.floor(sorted.length / 2);
                  let p50 = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
                  let mn = sorted[0], mx = sorted[sorted.length - 1];
                  const rankN = rawVals.filter((x) => (lowerBetter ? x < raw : x > raw)).length + 1;  // raw -> unit-independent
                  let u = unit, dv = raw;
                  if (units === "metric") {
                    const conv = field === "range_mi" ? 1.60934 : field === "weight_lb" || field === "max_load_lb" ? 0.453592 : null;
                    if (conv) { p50 *= conv; mn *= conv; mx *= conv; dv = Math.round(raw * conv); u = field === "range_mi" ? " km" : " kg"; }
                  }
                  const fmt = (x: number) => u === "$" ? `$${formatNumber(Math.round(x))}` : `${formatNumber(Math.round(x))}${u ?? ""}`;
                  const diff = Math.round(dv - p50);
                  const better = diff !== 0 && (lowerBetter ? diff < 0 : diff > 0);
                  const worse = diff !== 0 && !better;
                  const content: Record<string, React.ReactNode> = {
                    "Low": <span className="text-slate-500">{fmt(mn)}</span>,
                    "Median": <span className="text-slate-500">{fmt(p50)}</span>,
                    "High": <span className="text-slate-500">{fmt(mx)}</span>,
                    "This eBike": <span className={`inline-block whitespace-nowrap rounded ${badge} px-1 py-0.5 font-bold text-slate-900`}>{fmt(dv)}</span>,
                    "Diff vs Median": (
                      <span className={`inline-flex items-center gap-0.5 whitespace-nowrap font-semibold ${better ? "text-emerald-600" : worse ? "text-rose-500" : "text-slate-400"}`}>
                        {diff !== 0 && <svg className="h-2 w-2" viewBox="0 0 8 8" fill="currentColor" aria-hidden><path d={diff > 0 ? "M4 1l3 5H1z" : "M1 2h6l-3 5z"} /></svg>}
                        {diff === 0 ? "med" : fmt(Math.abs(diff))}
                      </span>
                    ),
                    "Rank Within Type": <span className="inline-flex justify-center"><RankBadge rank={rankN} total={rawVals.length} boltClass="h-4 w-4" dense /></span>,
                  };
                  return subCols.map((c, ci) => (
                    <td key={`${gi}-${ci}`} className={`${cellCls(ci === 0)} whitespace-nowrap`}>{content[c.l]}</td>
                  ));
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Mobile form of the Compare-page comparison: the table is INVERTED — one card per metric (the
// field name is the card header), and inside it a row per eBike showing that eBike's values.
export function HowEachComparesByMetric({
  models, allModels, units,
}: { models: Model[]; allModels: Model[]; units: UnitSystem }) {
  const valForModel = (m: Model, field: string): number | undefined =>
    field === "price" ? (m.price ?? m.price_min ?? undefined)
                      : (m.analysis?.specs_typed?.[field] as number | undefined);
  const cohorts = models.map((s) => {
    const pt = s.analysis?.primary_type;
    return allModels.filter((m) => (pt ? m.analysis?.primary_type === pt : true) && isAvailable(m));
  });
  const th = "px-1 py-1 text-center text-[9px] font-bold uppercase text-slate-400";
  const td = "border-t border-slate-100 px-1 py-1 text-center align-middle";
  return (
    <div className="space-y-3">
      {PERCENTILE_FIELDS.map(({ field, label, unit, icon, badge, lowerBetter }) => {
        if (!models.some((s) => valForModel(s, field) != null)) return null;
        return (
          <div key={field} className="overflow-hidden rounded-lg border border-slate-200">
            <div className="flex items-center gap-1.5 border-b border-slate-200 bg-slate-50/60 px-2 py-1.5 text-sm font-bold text-slate-800">
              <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${badge}`}>{icon}</span>
              {label}
            </div>
            <table className="w-full table-fixed text-[11px]">
              <thead>
                <tr>
                  <th className="w-[30%] px-2 py-1 text-left text-[9px] font-bold uppercase text-slate-400">eBike</th>
                  <th className={`${th} w-[11%]`}>Low</th>
                  <th className={`${th} w-[11%]`}>Med</th>
                  <th className={`${th} w-[11%]`}>High</th>
                  <th className={`${th} w-[15%] text-blue-700`}>This</th>
                  <th className={`${th} w-[12%]`}>Diff</th>
                  <th className={`${th} w-[10%]`}>Rank</th>
                </tr>
              </thead>
              <tbody>
                {models.map((s, i) => {
                  const rawVals = cohorts[i].map((m) => valForModel(m, field)).filter((x): x is number => typeof x === "number");
                  const raw = valForModel(s, field);
                  if (raw == null || !rawVals.length) {
                    return (
                      <tr key={s.id}>
                        <td className="border-t border-slate-100 px-2 py-1 text-left font-semibold leading-tight text-slate-700">{s.model}</td>
                        <td className={`${td} text-slate-300`} colSpan={6}>—</td>
                      </tr>
                    );
                  }
                  const sorted = [...rawVals].sort((a, b) => a - b);
                  const mid = Math.floor(sorted.length / 2);
                  let p50 = sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
                  let mn = sorted[0], mx = sorted[sorted.length - 1];
                  const rankN = rawVals.filter((x) => (lowerBetter ? x < raw : x > raw)).length + 1;  // raw -> unit-independent
                  let u = unit, dv = raw;
                  if (units === "metric") {
                    const conv = field === "range_mi" ? 1.60934 : field === "weight_lb" || field === "max_load_lb" ? 0.453592 : null;
                    if (conv) { p50 *= conv; mn *= conv; mx *= conv; dv = Math.round(raw * conv); u = field === "range_mi" ? " km" : " kg"; }
                  }
                  const fmt = (x: number) => u === "$" ? `$${formatNumber(Math.round(x))}` : `${formatNumber(Math.round(x))}${u ?? ""}`;
                  const diff = Math.round(dv - p50);
                  const better = diff !== 0 && (lowerBetter ? diff < 0 : diff > 0);
                  const worse = diff !== 0 && !better;
                  return (
                    <tr key={s.id}>
                      <td className="border-t border-slate-100 px-2 py-1 text-left font-semibold leading-tight text-slate-700">{s.model}</td>
                      <td className={`${td} text-slate-500`}>{fmt(mn)}</td>
                      <td className={`${td} text-slate-500`}>{fmt(p50)}</td>
                      <td className={`${td} text-slate-500`}>{fmt(mx)}</td>
                      <td className={td}><span className={`inline-block whitespace-nowrap rounded ${badge} px-1 py-0.5 font-bold text-slate-900`}>{fmt(dv)}</span></td>
                      <td className={td}>
                        <span className={`inline-flex items-center gap-0.5 whitespace-nowrap font-semibold ${better ? "text-emerald-600" : worse ? "text-rose-500" : "text-slate-400"}`}>
                          {diff !== 0 && <svg className="h-2 w-2" viewBox="0 0 8 8" fill="currentColor" aria-hidden><path d={diff > 0 ? "M4 1l3 5H1z" : "M1 2h6l-3 5z"} /></svg>}
                          {diff === 0 ? "med" : fmt(Math.abs(diff))}
                        </span>
                      </td>
                      <td className={td}><span className="inline-flex justify-center"><RankBadge rank={rankN} total={rawVals.length} boltClass="h-4 w-4" dense /></span></td>
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

// Shared legend (green/red direction + the bolt rating scale). `badge` = circled-number
// bolts (Compare page); default = the original N separate bolts (detail page).
export function HowItComparesLegend({ badge = false }: { badge?: boolean }) {
  return (
    <div className="mt-3 flex flex-col gap-y-1.5 rounded-lg border border-slate-200 p-3 text-xs text-slate-500">
      <span>
        <strong className="text-emerald-600">Green</strong> = better than median ·{" "}
        <strong className="text-rose-500">Red</strong> = worse (arrow = above/below median)
      </span>
      <span className={`inline-flex flex-wrap items-center gap-y-1 ${badge ? "gap-x-4" : "gap-x-2"}`}>
        <strong>Rating</strong> = standing on that metric:
        {([[4, "top 10%"], [3, "top 20%"], [2, "top 30%"], [1, "top 40%"]] as [number, string][]).map(([n, lbl]) => (
          <span key={lbl} className={`inline-flex items-center ${badge ? "gap-2" : "gap-1"}`}>
            {badge ? (
              <BoltBadge n={n} className="h-5 w-5" />
            ) : (
              <span className="inline-flex text-amber-500">
                {Array.from({ length: n }, (_, i) => <BoltIcon key={i} className="h-3.5 w-3.5" />)}
              </span>
            )}
            {lbl}
          </span>
        ))}
      </span>
    </div>
  );
}
