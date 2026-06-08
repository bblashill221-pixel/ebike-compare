import { useState, type ReactNode } from "react";
import type { EnumField, Filters, RangeField } from "../search/orama";
import { BOOL_FIELDS, type BoolField } from "../search/orama";
import { capitalize, labelize, titleCase } from "../format";
import { useShowSoldOut } from "../soldOut";
import { useUnits, inToCm, cmToIn, inToFtIn, ftInToIn, type UnitSystem } from "../units";

interface Props {
  facetOptions: Record<EnumField, string[]>;
  rangeBounds: Record<RangeField, [number, number]>;
  facetCounts: Record<string, Record<string, number>>;
  filters: Filters;
  setFilters: (f: Filters) => void;
}

const ENUM_SECTIONS: { field: EnumField; label: string }[] = [
  { field: "product_types", label: "Type" },
  { field: "brand", label: "Brand" },
  { field: "frame_style", label: "Frame style" },
  { field: "drive_type", label: "Drive" },
  { field: "brake_type", label: "Brakes" },
  { field: "frame_material", label: "Frame" },
  { field: "suspension", label: "Suspension" },
];

const RANGE_SECTIONS: { field: RangeField; label: string }[] = [
  { field: "price", label: "Price ($)" },
  { field: "battery_wh", label: "Battery (Wh)" },
  { field: "motor_w", label: "Motor (W)" },
  { field: "torque_nm", label: "Torque (Nm)" },
  { field: "range_mi", label: "Range (mi)" },
  { field: "weight_lb", label: "Weight (lb)" },
  { field: "gears", label: "Gears" },
];

const BOOL_LABELS: Record<BoolField, string> = {
  on_sale: "On sale",
  ul_listed: "UL listed",
  kids: "Exclude Kids Ebikes",
};

/** Collapsible filter section: clickable header with a chevron, open by default. */
function Section({
  label,
  open,
  onToggle,
  children,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <section>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center justify-between text-left"
      >
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
        <svg
          viewBox="0 0 20 20"
          fill="currentColor"
          className={`h-4 w-4 text-slate-400 transition-transform ${open ? "" : "-rotate-90"}`}
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06Z"
            clipRule="evenodd"
          />
        </svg>
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </section>
  );
}

export function FacetPanel({ facetOptions, rangeBounds, facetCounts, filters, setFilters }: Props) {
  const [showSoldOut, setShowSoldOut] = useShowSoldOut();
  const [units, setUnits] = useUnits();
  // sections the user has collapsed (everything starts expanded)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const toggleSection = (key: string) => setCollapsed({ ...collapsed, [key]: !collapsed[key] });

  const toggleEnum = (field: EnumField, value: string) => {
    const cur = filters.enums[field] ?? [];
    const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
    setFilters({ ...filters, enums: { ...filters.enums, [field]: next } });
  };
  const toggleBool = (field: BoolField) => {
    setFilters({ ...filters, bools: { ...filters.bools, [field]: !filters.bools[field] } });
  };
  const setRange = (field: RangeField, lo: number, hi: number) => {
    const [bLo, bHi] = rangeBounds[field];
    const ranges = { ...filters.ranges };
    if (lo <= bLo && hi >= bHi) delete ranges[field];
    else ranges[field] = [lo, hi];
    setFilters({ ...filters, ranges });
  };
  // Rider height is stored canonically in inches; shown as feet+inches (imperial)
  // or centimetres (metric). Empty input clears the filter (null).
  const setHeightIn = (inches: number | null) =>
    setFilters({ ...filters, riderHeightIn: inches });
  const ftin = filters.riderHeightIn == null ? null : inToFtIn(filters.riderHeightIn);
  const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));
  const setFtIn = (feet: string, inch: string) => {
    // feet drives the filter (1-7); clearing it clears the filter. Inches are
    // optional, 0-11. Both are clamped so out-of-range entries can't slip through.
    if (feet.trim() === "") return setHeightIn(null);
    const ft = clamp(Math.floor(Number(feet) || 1), 1, 7);
    const inch2 = inch.trim() === "" ? 0 : clamp(Math.floor(Number(inch) || 0), 0, 11);
    setHeightIn(ftInToIn(ft, inch2));
  };
  const cmValue = filters.riderHeightIn == null ? "" : inToCm(filters.riderHeightIn);
  const setCm = (raw: string) => {
    if (raw.trim() === "") return setHeightIn(null);
    const n = Number(raw);
    if (Number.isNaN(n)) return;
    // keep canonical inches unrounded so the metric search stays mm-precise
    setHeightIn(cmToIn(n));
  };
  const reset = () => {
    setFilters({ enums: {}, bools: {}, ranges: {}, riderHeightIn: null });
    setShowSoldOut(true);
  };

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">Filters</h2>
        <div className="flex items-center gap-3">
          <div className="flex overflow-hidden rounded border border-slate-300 text-xs" role="group" aria-label="Units">
            {(["imperial", "metric"] as UnitSystem[]).map((sys) => (
              <button
                key={sys}
                type="button"
                onClick={() => setUnits(sys)}
                aria-pressed={units === sys}
                className={`cursor-pointer px-2 py-0.5 ${units === sys ? "bg-brand-600 text-white" : "text-slate-600"}`}
              >
                {sys === "imperial" ? "ft/in" : "cm"}
              </button>
            ))}
          </div>
          <button type="button" onClick={reset} className="text-xs text-brand-600 hover:underline">
            Reset
          </button>
        </div>
      </div>

      {/* booleans (incl. "Exclude Kids Ebikes") */}
      <Section label="Features" open={!collapsed.features} onToggle={() => toggleSection("features")}>
        <div className="flex flex-wrap gap-2">
          {BOOL_FIELDS.map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => toggleBool(f)}
              className={`chip cursor-pointer ${filters.bools[f] ? "bg-brand-600 text-white" : ""}`}
            >
              {BOOL_LABELS[f]}
            </button>
          ))}
          {/* selected = include sold-out bikes (the default); deselect to hide
              unavailable models and their unavailable colors */}
          <button
            type="button"
            onClick={() => setShowSoldOut(!showSoldOut)}
            className={`chip cursor-pointer ${showSoldOut ? "bg-brand-600 text-white" : ""}`}
          >
            Sold out
          </button>
        </div>
      </Section>

      {/* rider height: keep bikes whose fit range (any frame size) includes the
          rider; bikes with no published range are kept (lenient) */}
      <Section label="Rider height" open={!collapsed.height} onToggle={() => toggleSection("height")}>
        <div className="flex items-center gap-2">
          {units === "metric" ? (
            <>
              <input
                type="number"
                inputMode="numeric"
                value={cmValue}
                min={0}
                onChange={(e) => setCm(e.target.value)}
                placeholder="e.g. 178"
                className="w-full rounded border-slate-300 text-sm"
                aria-label="Rider height (cm)"
              />
              <span className="text-xs text-slate-400">cm</span>
            </>
          ) : (
            <>
              <input
                type="number"
                inputMode="numeric"
                value={ftin ? ftin.ft : ""}
                min={1}
                max={7}
                onChange={(e) => setFtIn(e.target.value, ftin ? String(ftin.in) : "")}
                placeholder="ft"
                className="w-full rounded border-slate-300 text-sm"
                aria-label="Rider height (feet)"
              />
              <span className="text-xs text-slate-400">ft</span>
              <input
                type="number"
                inputMode="numeric"
                value={ftin ? ftin.in : ""}
                min={0}
                max={11}
                onChange={(e) => setFtIn(ftin ? String(ftin.ft) : "", e.target.value)}
                placeholder="in"
                className="w-full rounded border-slate-300 text-sm"
                aria-label="Rider height (inches)"
              />
              <span className="text-xs text-slate-400">in</span>
            </>
          )}
          {filters.riderHeightIn != null && (
            <button
              type="button"
              onClick={() => setHeightIn(null)}
              className="text-xs text-brand-600 hover:underline"
            >
              Clear
            </button>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-400">Bikes without a listed fit range are hidden.</p>
      </Section>

      {/* enum facets */}
      {ENUM_SECTIONS.map(({ field, label }) => {
        const options = facetOptions[field] ?? [];
        if (!options.length) return null;
        const counts = facetCounts[field] ?? {};
        const selected = filters.enums[field] ?? [];
        return (
          <Section key={field} label={label} open={!collapsed[field]} onToggle={() => toggleSection(field)}>
            <div className="space-y-1">
              {options.map((opt) => (
                <label key={opt} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={selected.includes(opt)}
                    onChange={() => toggleEnum(field, opt)}
                    className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span className="flex-1 truncate">
                    {/* product_types values are already display-formatted ("Mountain (eMTB)") */}
                    {field === "brand" ? capitalize(opt) : field === "product_types" ? opt : titleCase(opt)}
                  </span>
                  <span className="text-xs tabular-nums text-slate-400">{counts[opt] ?? 0}</span>
                </label>
              ))}
            </div>
          </Section>
        );
      })}

      {/* numeric ranges */}
      {RANGE_SECTIONS.map(({ field, label }) => {
        const [bLo, bHi] = rangeBounds[field] ?? [0, 0];
        if (bHi <= bLo) return null;
        const [lo, hi] = filters.ranges[field] ?? [bLo, bHi];
        return (
          <Section key={field} label={label} open={!collapsed[field]} onToggle={() => toggleSection(field)}>
            <div className="flex items-center gap-2">
              <input
                type="number"
                value={lo}
                min={bLo}
                max={bHi}
                onChange={(e) => setRange(field, Number(e.target.value), hi)}
                className="w-full rounded border-slate-300 text-sm"
                aria-label={`${labelize(field)} min`}
              />
              <span className="text-slate-400">–</span>
              <input
                type="number"
                value={hi}
                min={bLo}
                max={bHi}
                onChange={(e) => setRange(field, lo, Number(e.target.value))}
                className="w-full rounded border-slate-300 text-sm"
                aria-label={`${labelize(field)} max`}
              />
            </div>
          </Section>
        );
      })}
    </div>
  );
}
