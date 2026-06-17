import { useEffect, useRef, useState, type ReactNode } from "react";
import type { EnumField, Filters, RangeField } from "../search/orama";
import { BOOL_FIELDS, type BoolField } from "../search/orama";
import { capitalize, fieldLabel, labelize, titleCase } from "../format";
import { useShowSoldOut } from "../soldOut";
import { useUnits, inToCm, cmToIn, inToFtIn, ftInToIn, type UnitSystem } from "../units";
import { ENUM_SECTIONS, RANGE_SECTIONS, BOOL_LABELS } from "../filterMeta";
import { PRICE_TIERS, priceTierMax, priceTierLabel, matchPriceTier, SENSOR_OPTIONS } from "../filterMeta";

interface Props {
  facetOptions: Record<EnumField, string[]>;
  rangeBounds: Record<RangeField, [number, number]>;
  facetCounts: Record<string, Record<string, number>>;
  filters: Filters;
  setFilters: (f: Filters) => void;
}

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

/** Dual-handle range slider. Shows the live values while dragging but only
 *  commits the filter on release (pointer/touch/key up), so the result list
 *  isn't re-filtered on every intermediate value. */
function RangeSlider({
  bLo,
  bHi,
  value,
  unit,
  prefix,
  label,
  onCommit,
}: {
  bLo: number;
  bHi: number;
  value: [number, number];
  unit?: string | null;
  prefix?: string;
  label: string;
  onCommit: (lo: number, hi: number) => void;
}) {
  const [draft, setDraft] = useState<[number, number]>(value);
  // The range inputs' change events are CONTINUOUS (React batches them without a
  // synchronous flush), but pointer/touch-up is DISCRETE -- so a commit() that read
  // `draft` from the closure could fire with a stale value (e.g. the tier's $2000
  // instead of the just-dragged $1500). Mirror the live value into a ref, updated
  // synchronously on every change, and commit FROM the ref.
  const draftRef = useRef<[number, number]>(value);
  const movedRef = useRef(false);   // did a drag change the value since pointer-down?
  const update = (d: [number, number]) => { movedRef.current = true; draftRef.current = d; setDraft(d); };
  // resync the handles when the committed value changes externally (Reset, etc.)
  useEffect(() => { draftRef.current = value; setDraft(value); }, [value[0], value[1]]);
  const [lo, hi] = draft;
  // "modified" once narrowed from the full catalog bounds — drives whether the
  // thumbs (circles) show at all, and whether a bare click resets.
  const modified = lo > bLo || hi < bHi;
  const span = bHi - bLo;
  const pct = (v: number) => (span > 0 ? ((v - bLo) / span) * 100 : 0);
  const commit = () => onCommit(draftRef.current[0], draftRef.current[1]);
  // Pointer-up on a thumb with NO drag = a click on the "Reset" circle: snap the
  // WHOLE slider back to full range (clears the filter), so a handle can never get
  // locked at the absolute min/max. A drag commits the new range as usual.
  const end = () => {
    if (modified && !movedRef.current) {
      update([bLo, bHi]);
      onCommit(bLo, bHi);
    } else {
      commit();
    }
  };
  const fmt = (v: number) => `${prefix ?? ""}${v.toLocaleString()}${unit ? ` ${unit}` : ""}`;
  return (
    <div className="px-1">
      {/* live readout of the CURRENT selection (updates while dragging) */}
      <div className="mb-2 text-center text-xs font-semibold tabular-nums text-slate-700">
        {fmt(lo)} – {fmt(hi)}
      </div>
      <div className="range-track relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-slate-200" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-brand-500"
          style={{ left: `${pct(lo)}%`, right: `${100 - pct(hi)}%` }}
        />
        <input
          type="range"
          className={`range-dual${modified ? "" : " range-dual--pristine"}`}
          min={bLo}
          max={bHi}
          step={1}
          value={lo}
          aria-label={`${label} minimum`}
          title={modified ? "Reset" : undefined}
          onPointerDown={() => { movedRef.current = false; }}
          onChange={(e) => update([Math.min(Number(e.target.value), draftRef.current[1]), draftRef.current[1]])}
          onPointerUp={end}
          onKeyUp={commit}
          onTouchEnd={end}
        />
        <input
          type="range"
          className={`range-dual${modified ? "" : " range-dual--pristine"}`}
          min={bLo}
          max={bHi}
          step={1}
          value={hi}
          aria-label={`${label} maximum`}
          title={modified ? "Reset" : undefined}
          onPointerDown={() => { movedRef.current = false; }}
          onChange={(e) => update([draftRef.current[0], Math.max(Number(e.target.value), draftRef.current[0])])}
          onPointerUp={end}
          onKeyUp={commit}
          onTouchEnd={end}
        />
      </div>
      {/* fixed reference: the slider's true low/high (the full catalog range), so
          a selected sub-range never reads as if it were the whole scale */}
      <div className="mt-1 flex justify-between text-[10px] tabular-nums text-slate-400">
        <span>{fmt(bLo)}</span>
        <span>{fmt(bHi)}</span>
      </div>
    </div>
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
    setShowSoldOut(false); // back to the default: available-only
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
              {options.map((opt) => {
                const count = counts[opt] ?? 0;
                const isSel = selected.includes(opt);
                return (
                  <label
                    key={opt}
                    className="flex cursor-pointer items-center gap-2 text-sm text-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={isSel}
                      onChange={() => toggleEnum(field, opt)}
                      className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span className="flex-1 truncate">
                      {/* product_types values are already display-formatted ("Mountain (eMTB)") */}
                      {field === "brand" ? capitalize(opt) : field === "product_types" ? opt : titleCase(opt)}
                    </span>
                    <span className="text-xs tabular-nums text-slate-400">{count}</span>
                  </label>
                );
              })}
            </div>
          </Section>
        );
      })}

      {/* pedal-assist sensor: single-select (No Preference = unset) */}
      <Section label="Sensor" open={!collapsed.sensor_type} onToggle={() => toggleSection("sensor_type")}>
        <select
          value={filters.enums.sensor_type?.[0] ?? ""}
          onChange={(e) => {
            const v = e.target.value;
            setFilters({ ...filters, enums: { ...filters.enums, sensor_type: v ? [v] : [] } });
          }}
          aria-label="Pedal-assist sensor type"
          className="w-full rounded border-slate-300 text-sm"
        >
          {SENSOR_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </Section>

      {/* numeric ranges */}
      {RANGE_SECTIONS.map(({ field, label }) => {
        const [catLo, catHi] = rangeBounds[field] ?? [0, 0];
        if (catHi <= catLo) return null;
        const { unit } = fieldLabel(field);
        // Every range (price included) spans the full catalog bounds; the price
        // dropdown only sets the MAX, and the slider's low handle sets an optional min.
        const bLo = catLo;
        const bHi = catHi;
        const [lo, hi] = filters.ranges[field] ?? [bLo, bHi];
        // The price dropdown is derived from the current upper bound: the matching
        // max preset, or a transient "Custom" when the user dragged the high handle
        // off a preset value.
        const maxTier = field === "price" ? matchPriceTier(hi, catHi) : undefined;
        const priceSel = field === "price" ? (maxTier ? maxTier.label : "__custom") : "";
        return (
          <Section key={field} label={label} open={!collapsed[field]} onToggle={() => toggleSection(field)}>
            {field === "price" && (
              <select
                value={priceSel}
                onChange={(e) => {
                  const t = PRICE_TIERS.find((x) => x.label === e.target.value);
                  if (!t) return;
                  // set the MAX only; min resets to the catalog floor (drag to raise it)
                  setRange(field, catLo, priceTierMax(t, catHi));
                }}
                aria-label="Maximum budget"
                className="mb-3 w-full rounded border-slate-300 text-sm"
              >
                {!maxTier && (
                  <option value="__custom" disabled>
                    {`Custom (≤ $${Math.round(hi).toLocaleString()})`}
                  </option>
                )}
                {PRICE_TIERS.map((t) => (
                  <option key={t.label} value={t.label}>
                    {priceTierLabel(t)}
                  </option>
                ))}
              </select>
            )}
            <RangeSlider
              bLo={bLo}
              bHi={bHi}
              value={[lo, hi]}
              unit={unit}
              prefix={field === "price" ? "$" : undefined}
              label={labelize(field)}
              onCommit={(nlo, nhi) => setRange(field, nlo, nhi)}
            />
          </Section>
        );
      })}
    </div>
  );
}
