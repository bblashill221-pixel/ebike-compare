// Small presentation helpers shared across components.
import type { SpecValue } from "./types";
import type { UnitSystem } from "./units";

/** Capitalize only the first letter, leaving the rest untouched ("ride1up" -> "Ride1up"). */
export function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

/** The frame's colour for rendering the colour name (and its pill border) in the
 *  colour itself -- but ONLY for dark colours, which stay legible on a light product
 *  photo. Light colours wash out, so they return null and the caller renders the
 *  neutral default pill, exactly as for a bike with no hex. */
export function colorChipStyle(hex: string | null | undefined): { color: string } | null {
  if (!hex) return null;
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const h = m[1].length === 3 ? m[1].replace(/(.)/g, "$1$1") : m[1];
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  const lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  if (lum > 0.179) return null; // light colour -> neutral pill, like a no-hex bike
  return { color: `#${h}` };
}

export function titleCase(s: string): string {
  return s
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .trim();
}

/** snake_case field name -> human label, preserving common unit suffixes. */
const UNIT_LABEL: Record<string, string> = {
  wh: "Wh", kwh: "kWh", nm: "Nm", ah: "Ah", mm: "mm", cm: "cm", kg: "kg",
  lb: "lb", mph: "mph", kph: "kph", mi: "mi", km: "km", in: "in", deg: "deg",
  w: "W", v: "V",
};
export function labelize(field: string): string {
  const parts = field.split("_");
  const last = parts[parts.length - 1];
  if (UNIT_LABEL[last] && parts.length > 1) {
    return titleCase(parts.slice(0, -1).join(" ")) + ` (${UNIT_LABEL[last]})`;
  }
  return titleCase(field);
}

// System-dependent weight/distance units that flip with the unit toggle: shown
// as a value suffix ("45 mi") rather than a label suffix ("Range (mi)"). Fixed
// units (Wh, W, Nm, $, …) stay in the label via labelize().
const VALUE_SUFFIX_UNITS = new Set(["lb", "mi", "kg", "km"]);

/** A field's display label plus, for a value-suffix unit, the unit to append to
 *  its value: "range_mi" -> { label: "Range", unit: "mi" }; "battery_wh" ->
 *  { label: "Battery (Wh)", unit: null }. */
export function fieldLabel(field: string): { label: string; unit: string | null } {
  const parts = field.split("_");
  const last = parts[parts.length - 1];
  if (parts.length > 1 && VALUE_SUFFIX_UNITS.has(last)) {
    return { label: titleCase(parts.slice(0, -1).join(" ")), unit: UNIT_LABEL[last] };
  }
  return { label: labelize(field), unit: null };
}

/** Append a value-suffix unit to an already-formatted value, leaving the
 *  em-dash placeholder (and unitless values) untouched. */
export function withUnit(formatted: string, unit: string | null): string {
  return unit && formatted !== "—" ? `${formatted} ${unit}` : formatted;
}

export function formatPrice(n: number | null | undefined, currency = "USD"): string {
  if (n == null) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    }).format(n);
  } catch {
    return `$${Math.round(n)}`;
  }
}

export function formatNumber(n: number, digits = 0, grouping = true): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    useGrouping: grouping,
  }).format(n);
}

/** Fields whose key IS the unit: render "800 lumens" / "70 lux", not "Lumens: 800". */
const VALUE_UNIT: Record<string, string> = { lumens: "lumens", lux: "lux" };

const IMPERIAL_UNITS = new Set(["lb", "mph", "mi", "in"]);
const METRIC_UNITS = new Set(["kg", "kph", "km", "mm", "cm"]);

const IMP_TOKEN = /(?:inch(?:es)?|\bin\b|″|"|\blbs?\b|\bmph\b|\bmiles?\b|\bmi\b)/i;
const MET_TOKEN = /\b(?:cm|mm|kg|km\/?h|kph|km)\b/i;

/** Many scraped strings carry the same measurement in both systems, usually
 *  "<imperial> (<metric>)" or "<metric> (<imperial>)" (e.g. "45.2 inches (115
 *  cm)"). Keep only the active system's side; leave non-unit parentheticals and
 *  single-system strings alone. */
function preferUnitInString(s: string, system: UnitSystem): string {
  return s.replace(/^(.*?)\s*\(([^)]+)\)(.*)$/, (full, before, paren, after) => {
    const bImp = IMP_TOKEN.test(before), bMet = MET_TOKEN.test(before);
    const pImp = IMP_TOKEN.test(paren), pMet = MET_TOKEN.test(paren);
    let keep: string | null = null;
    if (bImp && pMet && !bMet && !pImp) keep = system === "metric" ? paren : before;
    else if (bMet && pImp && !bImp && !pMet) keep = system === "metric" ? before : paren;
    if (keep == null) return full; // not a clean imperial/metric pair
    return (keep.trim() + after).trim();
  });
}

/** Of paired imperial/metric fields of one measurement (weight_lb + weight_kg,
 *  range_mi + range_km), the keys to hide so only the active unit system is
 *  shown. Single-unit fields are always kept. Used both within a parsed
 *  component object and across a spec group's sibling rows (SpecTable). */
export function hiddenUnitKeys(keys: string[], system: UnitSystem): Set<string> {
  const suffix = (k: string) => k.slice(k.lastIndexOf("_") + 1);
  const hide = new Set<string>();
  for (const k of keys) {
    const suf = suffix(k);
    const isImp = IMPERIAL_UNITS.has(suf);
    const isMet = METRIC_UNITS.has(suf);
    if (!isImp && !isMet) continue;
    const prefix = k.slice(0, k.length - suf.length); // includes trailing "_"
    const paired = keys.some((j) => {
      if (j === k || !j.startsWith(prefix)) return false;
      const s = suffix(j);
      return isImp ? METRIC_UNITS.has(s) : IMPERIAL_UNITS.has(s);
    });
    if (paired && ((system === "imperial" && isMet) || (system === "metric" && isImp))) {
      hide.add(k);
    }
  }
  return hide;
}

/** Render a parsed spec value (string / number / dict / list) to readable text.
 *  `system` picks which side of any paired imperial/metric field to show. */
export function formatSpecValue(value: SpecValue, system: UnitSystem = "imperial"): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return formatNumber(value, 2);
  if (typeof value === "string") return preferUnitInString(value, system);
  if (Array.isArray(value)) return value.map((x) => formatSpecValue(x, system)).join(", ");
  // object: prefer a "details" key, then join the rest as "Label: value".
  const obj = value as Record<string, SpecValue>;
  const hide = hiddenUnitKeys(Object.keys(obj), system);
  const parts: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v == null || v === "" || hide.has(k)) continue;
    if (k === "details") {
      parts.push(formatSpecValue(v, system));
    } else if (k === "by_size" && v && typeof v === "object" && !Array.isArray(v)) {
      // per-frame-size attributes -> "S/M: Width 780 mm, Rise 20 mm; L/XL: …"
      parts.push(
        Object.entries(v as Record<string, SpecValue>)
          .map(([size, attrs]) => `${size}: ${formatSpecValue(attrs, system)}`)
          .join("; "),
      );
    } else if (VALUE_UNIT[k] && (typeof v === "number" || typeof v === "string")) {
      parts.push(`${formatSpecValue(v, system)} ${VALUE_UNIT[k]}`);
    } else {
      const { label, unit } = fieldLabel(k);
      parts.push(`${label}: ${withUnit(formatSpecValue(v, system), unit)}`);
    }
  }
  return parts.join(" · ") || "—";
}
