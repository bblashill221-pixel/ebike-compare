// Small presentation helpers shared across components.
import type { SpecValue } from "./types";

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

export function formatNumber(n: number, digits = 0): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(n);
}

/** Render a parsed spec value (string / number / dict / list) to readable text. */
export function formatSpecValue(value: SpecValue): string {
  if (value == null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return formatNumber(value, 2);
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(formatSpecValue).join(", ");
  // object: prefer a "details" key, then join the rest as "Label: value".
  const obj = value as Record<string, SpecValue>;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v == null || v === "") continue;
    if (k === "details") {
      parts.push(formatSpecValue(v));
    } else {
      parts.push(`${labelize(k)}: ${formatSpecValue(v)}`);
    }
  }
  return parts.join(" · ") || "—";
}
