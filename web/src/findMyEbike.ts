import type { Filters, RangeField } from "./search/orama";
import { PRICE_TIERS, priceTierLabel } from "./filterMeta";

// "Find My eBike" beginner quiz. Each dropdown choice carries the *technical*
// filter params it should contribute to the Browse URL; the labels stay
// jargon-free. Choosing "No preference" (always first) contributes nothing, so
// the user can answer all or just a few questions.

export interface QuizChoice {
  label: string;
  /** Query params this choice merges into the Browse link. */
  params: Record<string, string>;
}

export interface QuizQuestion {
  id: string;
  label: string;
  help?: string;
  choices: QuizChoice[];
}

const NONE: QuizChoice = { label: "No preference", params: {} };

// Budget choices mirror the Browse price filter's PRICE_TIERS (max-only): each is a
// "≤ $X" ceiling emitting price_max (no floor), so the handoff lands on [catalog
// floor, X] and multi-select widens to the largest ceiling.
const BUDGET_CHOICES: QuizChoice[] = [
  NONE,
  ...PRICE_TIERS.filter((t) => t.max != null).map((t) => ({
    label: priceTierLabel(t),             // "≤ $4,000"
    params: { price_max: String(t.max) },
  })),
];

// NOTE: numeric thresholds (torque/range/load/price) are first-pass and meant to
// be tuned against the dataset so no bucket comes back empty.
export const QUESTIONS: QuizQuestion[] = [
  {
    id: "use",
    label: "What Will You Use It For? (determining type)",
    choices: [
      NONE,
      { label: "Getting around town", params: { type: "Commuter / Urban" } },
      { label: "Trails & off-road", params: { type: "Mountain (eMTB)" } },
      { label: "Hauling cargo or kids", params: { type: "Cargo" } },
      { label: "Casual cruising", params: { type: "Cruiser" } },
    ],
  },
  {
    id: "budget",
    label: "What's Your Maximum Budget? (can be adjusted later)",
    choices: BUDGET_CHOICES,
  },
  {
    id: "height",
    label: "How Tall Are You?",
    help: "Shows bikes that fit your height.",
    choices: [
      NONE,
      { label: "Under 5'4\"", params: { height_in: "62" } },
      { label: "5'4\" – 5'8\"", params: { height_in: "66" } },
      { label: "5'9\" – 6'0\"", params: { height_in: "70" } },
      { label: "6'0\" – 6'2\"", params: { height_in: "73" } },
      { label: "6'2\"+", params: { height_in: "75" } },
    ],
  },
  {
    id: "weight",
    label: "What's Your Weight?",
    help: "Shows bikes rated to carry your weight.",
    choices: [
      NONE,
      { label: "Under 150 lbs", params: { load_min: "150" } },
      { label: "150 – 200 lbs", params: { load_min: "200" } },
      { label: "200 – 250 lbs", params: { load_min: "250" } },
      { label: "250 – 300 lbs", params: { load_min: "300" } },
      { label: "300+ lbs", params: { load_min: "350" } },
    ],
  },
  {
    id: "range",
    label: "What Is the Maximum Distance You Want to Ride?",
    help: "On a single charge.",
    choices: [
      NONE,
      { label: "Up to 25 miles", params: { range_min: "25" } },
      { label: "Up to 50 miles", params: { range_min: "50" } },
      { label: "Up to 60 miles", params: { range_min: "60" } },
      { label: "60+ miles", params: { range_min: "65" } },
    ],
  },
  {
    id: "terrain",
    label: "What Kind of Terrain? (determining torque requirements)",
    choices: [
      NONE,
      { label: "Mostly flat", params: {} },
      { label: "Moderate hills", params: { torque_min: "50" } },
      { label: "Steep hills", params: { torque_min: "65" } },
    ],
  },
  {
    id: "bikeweight",
    label: "How Heavy of an eBike Are You Comfortable With? (determining weight constraints)",
    choices: [
      NONE, // "N/A" = leave unchecked
      { label: "30 lb or less", params: { weight_max: "30" } },
      { label: "30 to 40 lb", params: { weight_max: "40" } },
      { label: "Up to 50 lb", params: { weight_max: "50" } },
      // "50+ lb" = comfortable with any weight -> no upper bound -> don't filter on weight
      { label: "50+ lb", params: {} },
    ],
  },
  {
    id: "effort",
    label: "How Much Do You Want to Pedal?",
    help: "A torque sensor rewards pedaling effort; a cadence sensor only needs the pedals turning.",
    choices: [
      NONE,
      { label: "Always pedaling", params: { sensor: "torque" } },
      { label: "Sometimes pedaling", params: { sensor: "torque + cadence" } },
      { label: "Rarely pedaling", params: { sensor: "torque + cadence,cadence" } },
    ],
  },
  {
    id: "access",
    label: "Easy Access?",
    help: "A low step-through frame is easier to get on and off.",
    choices: [
      NONE,
      { label: "Yes, easy step-through", params: { frame: "Step-Thru" } },
    ],
  },
  {
    id: "folding",
    label: "Do You Need an eBike That Folds?",
    choices: [
      NONE,
      { label: "Yes, it must fold", params: { folding: "1" } },
    ],
  },
];

/**
 * Build the Browse query string from the quiz answers. Enum keys (type/sensor/frame)
 * merge to a de-duped CSV; numeric keys collapse to the most permissive bound; price
 * spans the lowest selected floor to the highest selected ceiling (an open end only set
 * when every selected price tier supplies it). Shared by the live count, the persist-on-
 * change writer, and the final hand-off so all three agree.
 */
export function searchFromAnswers(answers: Record<string, number[]>): string {
  const vals: Record<string, string[]> = {};
  let priceN = 0;
  const pMin: number[] = [];
  const pMax: number[] = [];
  for (const q of QUESTIONS) {
    for (const i of answers[q.id] ?? []) {
      const p = q.choices[i]?.params;
      if (!p) continue;
      if ("price_min" in p || "price_max" in p) {
        priceN++;
        if (p.price_min != null) pMin.push(Number(p.price_min));
        if (p.price_max != null) pMax.push(Number(p.price_max));
      }
      for (const [k, v] of Object.entries(p)) {
        if (k === "price_min" || k === "price_max") continue;
        (vals[k] ??= []).push(v);
      }
    }
  }
  const sp = new URLSearchParams();
  if (priceN) {
    if (pMin.length === priceN) sp.set("price_min", String(Math.min(...pMin)));
    if (pMax.length === priceN) sp.set("price_max", String(Math.max(...pMax)));
  }
  for (const [k, list] of Object.entries(vals)) {
    const nums = list.map(Number);
    if (nums.every((n) => !Number.isNaN(n))) {
      sp.set(k, String(k.endsWith("_max") ? Math.max(...nums) : Math.min(...nums)));
    } else {
      sp.set(k, [...new Set(list.flatMap((v) => v.split(",")))].join(","));
    }
  }
  return sp.toString();
}

/** Query-param keys the quiz can emit (Browse strips these after hydrating). */
export const QUIZ_PARAM_KEYS = [
  "type",
  "frame",
  "sensor",
  "folding",
  "price_min",
  "price_max",
  "range_min",
  "torque_min",
  "load_min",
  "height_in",
  "weight_min",
  "weight_max",
] as const;

export function hasQuizParams(sp: URLSearchParams): boolean {
  return QUIZ_PARAM_KEYS.some((k) => sp.has(k));
}

// "Hide this screen" preference: when set, a fresh landing skips the quiz and
// goes straight to Browse (see the one-time redirect in App).
const SKIP_KEY = "find-my-ebike:skip";

export function shouldSkipQuiz(): boolean {
  try {
    return localStorage.getItem(SKIP_KEY) === "true";
  } catch {
    return false;
  }
}

export function setSkipQuiz(value: boolean): void {
  try {
    localStorage.setItem(SKIP_KEY, value ? "true" : "false");
  } catch {
    /* storage blocked: the skip just won't persist */
  }
}

/**
 * Translate quiz query params into a Browse Filters object. Range params set one
 * end of the band and inherit the other from `rangeBounds`, so a "max $2,500"
 * answer becomes [bound-low, 2500].
 */
export function filtersFromParams(
  sp: URLSearchParams,
  rangeBounds: Record<RangeField, [number, number]>,
): Filters {
  const filters: Filters = { enums: {}, bools: {}, ranges: {}, riderHeightIn: null };

  const csv = (raw: string | null) => (raw ? raw.split(",").filter(Boolean) : []);
  const types = csv(sp.get("type"));
  if (types.length) filters.enums.product_types = types;
  const frames = csv(sp.get("frame"));
  if (frames.length) filters.enums.frame_style = frames;
  const sensors = csv(sp.get("sensor"));
  if (sensors.length) filters.enums.sensor_type = sensors;

  const setBand = (field: RangeField, minRaw: string | null, maxRaw: string | null) => {
    const bounds = rangeBounds[field];
    if (!bounds) return;
    let [lo, hi] = bounds;
    let touched = false;
    const min = Number(minRaw);
    const max = Number(maxRaw);
    if (minRaw != null && !Number.isNaN(min)) { lo = min; touched = true; }
    if (maxRaw != null && !Number.isNaN(max)) { hi = max; touched = true; }
    if (touched) filters.ranges[field] = [lo, hi];
  };
  setBand("price", sp.get("price_min"), sp.get("price_max"));
  // a budget answer carries a ceiling -> seed the dropdown (scopes the price slider)
  const pMax = Number(sp.get("price_max"));
  if (sp.get("price_max") != null && !Number.isNaN(pMax)) filters.priceCeiling = pMax;
  setBand("range_mi", sp.get("range_min"), null);
  setBand("torque_nm", sp.get("torque_min"), null);
  setBand("max_load_lb", sp.get("load_min"), null);
  setBand("weight_lb", sp.get("weight_min"), sp.get("weight_max"));

  const h = Number(sp.get("height_in"));
  if (sp.get("height_in") != null && !Number.isNaN(h)) filters.riderHeightIn = h;

  // folding is a boolean feature filter (not a product type)
  if (sp.get("folding")) filters.bools.folding = true;

  return filters;
}

/**
 * Inverse of the quiz's forward mapping: given the active Browse `Filters`, pick the
 * quiz answer (choice index) that produced each filter value, so navigating back to
 * the quiz pre-selects the radios matching the current listing. Choices with no params
 * (`No preference`, terrain "Mostly flat") carry no signal and stay unanswered, as do
 * filters the quiz can't express (brand, sold-out, a non-quiz product type, a custom
 * slider value that matches no tier).
 */
function paramSatisfied(key: string, val: string, f: Filters): boolean {
  const n = Number(val);
  const has = (field: keyof Filters["enums"], v: string) => (f.enums[field] ?? []).includes(v);
  switch (key) {
    case "type":
      return val.split(",").every((v) => has("product_types", v));
    case "frame":
      return val.split(",").every((v) => has("frame_style", v));
    case "sensor": {
      const want = new Set(val.split(","));
      const have = new Set(f.enums.sensor_type ?? []);
      return want.size === have.size && [...want].every((v) => have.has(v));
    }
    case "price_max":
      return (f.priceCeiling ?? f.ranges.price?.[1]) === n;
    case "price_min":
      return f.ranges.price?.[0] === n;
    case "range_min":
      return f.ranges.range_mi?.[0] === n;
    case "torque_min":
      return f.ranges.torque_nm?.[0] === n;
    case "load_min":
      return f.ranges.max_load_lb?.[0] === n;
    case "weight_min":
      return f.ranges.weight_lb?.[0] === n;
    case "weight_max":
      return f.ranges.weight_lb?.[1] === n;
    case "height_in":
      return f.riderHeightIn === n;
    case "folding":
      return f.bools.folding === true;
    default:
      return false;
  }
}

export function answersFromFilters(f: Filters | null): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  if (!f) return out;
  for (const q of QUESTIONS) {
    for (let i = 0; i < q.choices.length; i++) {
      const params = q.choices[i].params;
      const keys = Object.keys(params);
      if (!keys.length) continue; // "No preference" / "Mostly flat": nothing to reverse
      if (keys.every((k) => paramSatisfied(k, params[k], f))) {
        out[q.id] = [i];
        break;
      }
    }
  }
  return out;
}
