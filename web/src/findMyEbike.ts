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
      { label: "50+ lb", params: { weight_min: "50" } },
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
      { label: "Yes, it must fold", params: { type: "Folding" } },
    ],
  },
];

/** Query-param keys the quiz can emit (Browse strips these after hydrating). */
export const QUIZ_PARAM_KEYS = [
  "type",
  "frame",
  "sensor",
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
  setBand("range_mi", sp.get("range_min"), null);
  setBand("torque_nm", sp.get("torque_min"), null);
  setBand("max_load_lb", sp.get("load_min"), null);
  setBand("weight_lb", sp.get("weight_min"), sp.get("weight_max"));

  const h = Number(sp.get("height_in"));
  if (sp.get("height_in") != null && !Number.isNaN(h)) filters.riderHeightIn = h;

  return filters;
}
