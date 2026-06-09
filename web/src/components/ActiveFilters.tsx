import type { Filters } from "../search/orama";
import { BOOL_FIELDS } from "../search/orama";
import { ENUM_SECTIONS, RANGE_SECTIONS, BOOL_LABELS } from "../filterMeta";
import { capitalize, formatNumber, titleCase } from "../format";
import { useUnits, inToCm, inToFtIn } from "../units";
import { useShowSoldOut } from "../soldOut";

type Pill = { key: string; label: string; onRemove: () => void };

/** A removable pill for every active filter value, shown by the result count.
 * Clicking the × clears just that one value — a fast, central alternative to
 * hunting it down in the side panel. */
export function ActiveFilters({
  filters,
  setFilters,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
}) {
  const [units] = useUnits();
  const [showSoldOut, setShowSoldOut] = useShowSoldOut();
  const pills: Pill[] = [];

  // enum facets — one pill per selected value (brands, types, …)
  for (const { field, label } of ENUM_SECTIONS) {
    const vals = filters.enums[field] ?? [];
    for (const v of vals) {
      const disp = field === "brand" ? capitalize(v) : field === "product_types" ? v : titleCase(v);
      pills.push({
        key: `enum:${field}:${v}`,
        label: `${label}: ${disp}`,
        onRemove: () =>
          setFilters({
            ...filters,
            enums: { ...filters.enums, [field]: vals.filter((x) => x !== v) },
          }),
      });
    }
  }

  // numeric ranges — present only when narrowed from the full bounds
  for (const { field, label } of RANGE_SECTIONS) {
    const r = filters.ranges[field];
    if (!r) continue;
    const [lo, hi] = r;
    const val = field === "price" ? `$${formatNumber(lo)}–$${formatNumber(hi)}` : `${formatNumber(lo)}–${formatNumber(hi)}`;
    const name = label.replace(/\s*\(.*\)$/, "");
    pills.push({
      key: `range:${field}`,
      label: `${name}: ${val}`,
      onRemove: () => {
        const ranges = { ...filters.ranges };
        delete ranges[field];
        setFilters({ ...filters, ranges });
      },
    });
  }

  // boolean features
  for (const f of BOOL_FIELDS) {
    if (!filters.bools[f]) continue;
    pills.push({
      key: `bool:${f}`,
      label: BOOL_LABELS[f],
      onRemove: () => setFilters({ ...filters, bools: { ...filters.bools, [f]: false } }),
    });
  }

  // rider height (canonical inches; shown in the active unit)
  if (filters.riderHeightIn != null) {
    const h = filters.riderHeightIn;
    const disp = units === "metric" ? `${inToCm(h)} cm` : `${inToFtIn(h).ft}'${inToFtIn(h).in}"`;
    pills.push({
      key: "height",
      label: `Fits: ${disp}`,
      onRemove: () => setFilters({ ...filters, riderHeightIn: null }),
    });
  }

  // sold-out hidden (the non-default state of the toggle)
  if (!showSoldOut) {
    pills.push({ key: "soldout", label: "In stock only", onRemove: () => setShowSoldOut(true) });
  }

  if (!pills.length) return null;

  const clearAll = () => {
    setFilters({ enums: {}, bools: {}, ranges: {}, riderHeightIn: null });
    setShowSoldOut(false); // default: available-only
  };

  // No wrapper element: pills flow inline within the parent's flex row (next to
  // the result count), wrapping as needed.
  return (
    <>
      {pills.map((p) => (
        <button
          key={p.key}
          type="button"
          onClick={p.onRemove}
          className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-xs text-brand-700 hover:bg-brand-100"
          title={`Remove ${p.label}`}
        >
          <span>{p.label}</span>
          <svg viewBox="0 0 20 20" fill="currentColor" className="h-3 w-3 text-brand-400" aria-hidden="true">
            <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
          </svg>
        </button>
      ))}
      {pills.length > 1 && (
        <button type="button" onClick={clearAll} className="text-xs text-brand-600 hover:underline">
          Clear all
        </button>
      )}
    </>
  );
}
