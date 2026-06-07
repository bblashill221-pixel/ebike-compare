import type { EnumField, Filters, RangeField } from "../search/orama";
import { BOOL_FIELDS, type BoolField } from "../search/orama";
import { capitalize, labelize, titleCase } from "../format";

interface Props {
  facetOptions: Record<EnumField, string[]>;
  rangeBounds: Record<RangeField, [number, number]>;
  facetCounts: Record<string, Record<string, number>>;
  filters: Filters;
  setFilters: (f: Filters) => void;
}

const ENUM_SECTIONS: { field: EnumField; label: string }[] = [
  { field: "brand", label: "Brand" },
  { field: "product_type", label: "Type" },
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
  removable_battery: "Removable battery",
  ul_listed: "UL listed",
};

export function FacetPanel({ facetOptions, rangeBounds, facetCounts, filters, setFilters }: Props) {
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
  const reset = () => setFilters({ enums: {}, bools: {}, ranges: {} });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">Filters</h2>
        <button type="button" onClick={reset} className="text-xs text-brand-600 hover:underline">
          Reset
        </button>
      </div>

      {/* booleans */}
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
      </div>

      {/* enum facets */}
      {ENUM_SECTIONS.map(({ field, label }) => {
        const options = facetOptions[field] ?? [];
        if (!options.length) return null;
        const counts = facetCounts[field] ?? {};
        const selected = filters.enums[field] ?? [];
        return (
          <fieldset key={field}>
            <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {label}
            </legend>
            <div className="max-h-44 space-y-1 overflow-auto pr-1">
              {options.map((opt) => (
                <label key={opt} className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={selected.includes(opt)}
                    onChange={() => toggleEnum(field, opt)}
                    className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span className="flex-1 truncate">
                    {field === "brand" ? capitalize(opt) : titleCase(opt)}
                  </span>
                  <span className="text-xs tabular-nums text-slate-400">{counts[opt] ?? 0}</span>
                </label>
              ))}
            </div>
          </fieldset>
        );
      })}

      {/* numeric ranges */}
      {RANGE_SECTIONS.map(({ field, label }) => {
        const [bLo, bHi] = rangeBounds[field] ?? [0, 0];
        if (bHi <= bLo) return null;
        const [lo, hi] = filters.ranges[field] ?? [bLo, bHi];
        return (
          <div key={field}>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
              {label}
            </div>
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
          </div>
        );
      })}
    </div>
  );
}
