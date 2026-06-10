// Small presentation helpers shared across components.
import type { SpecValue } from "./types";
import type { UnitSystem } from "./units";

/** Capitalize only the first letter, leaving the rest untouched ("ride1up" -> "Ride1up"). */
export function capitalize(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
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
    } else if (VALUE_UNIT[k] && (typeof v === "number" || typeof v === "string")) {
      parts.push(`${formatSpecValue(v, system)} ${VALUE_UNIT[k]}`);
    } else {
      parts.push(`${labelize(k)}: ${formatSpecValue(v, system)}`);
    }
  }
  return parts.join(" · ") || "—";
}
