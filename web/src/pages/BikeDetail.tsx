import { useEffect, useRef, useState } from "react";
import { Link, useParams, useNavigate, useLocation } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { ColorSwatches, upchargeText } from "../components/ColorSwatches";
import { useColorSelection, defaultColorIndex, colorSoldOut, soldOutColors } from "../colorSelection";
import { isAvailable, useShowSoldOut } from "../soldOut";
import { useCompare } from "../compare/CompareContext";
import { formatPrice, formatNumber, titleCase, groupLabel, colorChipStyle, fieldLabel } from "../format";
import { useUnits, inToFtIn } from "../units";
import { colorPrices, defaultDims, lowestPrice, variantPrice } from "../pricing";
import { VariantPicker } from "../components/VariantPicker";
import { Price } from "../components/Price";
import { BuildGrade } from "../components/BuildGrade";
import { ValuePips } from "../components/ValueMeter";
import type { Model } from "../types";
import { SpecialFeaturesCard } from "../components/UncommonFeaturesList";
import { HighlightsList } from "../components/HighlightsList";
import { SpecTable } from "../components/SpecTable";
import { AffiliateLink } from "../components/AffiliateLink";
import { displayName, primaryImage } from "../components/BikeCard";
import { HowItCompares, HowItComparesLegend } from "../components/HowItCompares";
import { BatteryIcon, BoltIcon, MotorIcon, RangeIcon, RiderHeightIcon, TagIcon, TorqueIcon, WeightIcon } from "../components/icons";

const GROUP_ORDER = [
  "general_info",
  "ebike_system",
  "water_resistance",
  "frameset",
  "wheelset",
  "brakes",
  "drivetrain",
  "cockpit",
  "geometry",
  // NB included_accessories is deliberately not a spec group here — the
  // dedicated Accessories card below renders it (free first, then the brand's
  // paid add-ons with prices).
];


// Per-frame-size geometry: normalize structures each per-size attribute as a
// {sizeLabel: value} map (e.g. {"17\"": "432mm", "19\"": "470mm"}); a single
// shared figure stays a string. Build one row per attribute, aligned to `sizes`.
// A trailing LENGTH unit on a geometry value ("44.4 cm", '17.5"'); angles ("73.5°")
// carry no length unit and keep their ° on the value.
const GEO_LEN_UNIT = /\s*(cm|mm|inches|inch|in|")$/i;
const geoUnitLabel = (raw: string) =>
  raw === '"' ? "in" : raw.toLowerCase().replace(/inch(es)?/, "in");

function geometryRows(geo: Record<string, unknown>, sizes: string[]) {
  const rows: { label: string; vals: string[]; span: boolean }[] = [];
  for (const [k, v] of Object.entries(geo)) {
    let label = fieldLabel(k).label;
    let vals: string[];
    let span: boolean;
    if (v && typeof v === "object" && !Array.isArray(v)) {
      const dict = v as Record<string, unknown>;
      vals = sizes.map((sz) => (dict[sz] == null ? "" : String(dict[sz])));
      if (!vals.some(Boolean)) continue;
      span = false;
    } else if (typeof v === "string" && /\d/.test(v)) {
      vals = [v.trim()]; // shared across sizes
      span = true;
    } else {
      continue;
    }
    // When a row's values share one length unit (cm/mm/in), move it onto the
    // label ("Seat Tube Length (cm)") and strip it from each value; angle rows
    // (°) are left untouched.
    const units = new Set<string>();
    for (const val of vals) {
      const m = val.match(GEO_LEN_UNIT);
      if (m) units.add(geoUnitLabel(m[1]));
    }
    if (units.size === 1) {
      label = `${label} (${[...units][0]})`;
      vals = vals.map((val) => val.replace(GEO_LEN_UNIT, "").trim());
    }
    rows.push({ label, vals, span });
  }
  return rows;
}

function geoTableHasRows(geo: Record<string, unknown>, sizes: string[]): boolean {
  return geometryRows(geo, sizes).length > 0;
}

function GeometryTable({ geo, sizes }: { geo: Record<string, unknown>; sizes: string[] }) {
  const rows = geometryRows(geo, sizes);
  if (!rows.length) return null;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs font-medium text-slate-400">
          <th className="w-2/5 py-1 pr-3" />
          {sizes.map((s) => (
            <th key={s} className="py-1 pr-3">{s}</th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {rows.map((r) => (
          <tr key={r.label} className="align-top">
            <th className="w-2/5 py-1.5 pr-3 text-left font-medium text-slate-500">{r.label}</th>
            {r.span ? (
              <td className="py-1.5 pr-3 text-slate-800" colSpan={sizes.length}>{r.vals[0]}</td>
            ) : (
              r.vals.map((val, i) => (
                <td key={i} className="py-1.5 pr-3 text-slate-800">{val}</td>
              ))
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BikeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // Back returns to wherever the user came from BEFORE entering the detail flow (browse,
  // compare, ...), ignoring all in-page activity. "Other versions" links use `replace`, so
  // hopping between sibling detail pages never grows history — it stays [referrer, detail],
  // and navigate(-1) lands on the referrer. We capture "did we arrive via in-app nav" ONCE
  // at mount (a ref, so a later sibling `replace` can't flip location.key out of "default"
  // on a direct load); location.key === "default" only on a fresh load / external link.
  const enteredInApp = useRef(location.key !== "default");
  const goBack = () => (enteredInApp.current ? navigate(-1) : navigate("/"));
  const { byId, models, brandByName, status } = useData();
  const { has, toggle, isFull } = useCompare();
  const model = id ? byId.get(decodeURIComponent(id)) : undefined;
  // selection is shared with the browse cards (and persists for the session);
  // a fresh visit defaults to the first in-stock colorway
  const [showSoldOut] = useShowSoldOut();
  const [units] = useUnits();
  const [color, setColor] = useColorSelection(
    model?.id,
    model?.colors?.length ?? 0,
    model ? defaultColorIndex(model) : 0,
  );
  // hide sold-out colors when the "Sold out" filter is off (unless that would
  // leave nothing — a fully sold-out model keeps its swatches)
  const sold = model ? soldOutColors(model) : new Set<string>();
  const availCount = (model?.colors ?? []).filter(
    (c) => !sold.has((c.name ?? "").toLowerCase()),
  ).length;
  const hiddenColors = model && !showSoldOut && availCount > 0 ? sold : undefined;
  useEffect(() => {
    if (model && hiddenColors && colorSoldOut(model, color)) setColor(defaultColorIndex(model));
  }, [hiddenColors, color, model, setColor]);
  // non-color option selections (e.g. frame type); default to the cheapest config
  const [dims, setDims] = useState<Record<string, string>>({});
  // some brands list 100+ paid add-ons; collapsed by default
  const [allAccessories, setAllAccessories] = useState(false);
  useEffect(() => {
    setDims(model ? defaultDims(model) : {});
    // open at the top — without this the page inherits the browse grid's
    // scroll offset (Browse saves its own position and restores it on return)
    window.scrollTo(0, 0);
  }, [model?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (status === "loading") return <Center>Loading…</Center>;
  if (!model) {
    return (
      <Center>
        <div className="text-center">
          <p className="mb-3">That eBike could not be found.</p>
          <Link to="/" className="btn-primary">Back to browse</Link>
        </div>
      </Center>
    );
  }

  // The "how it compares" distributions are drawn from the bike's PRIMARY-TYPE
  // peers (falling back to the fleet if that cohort's stats are missing).
  const primaryType = model.analysis?.primary_type;
  const compareHeading = primaryType
    ? `How It Compares to All Other ${primaryType} Bikes`
    : "How It Compares to the Fleet";

  // Cohort = same-type bikes you can actually BUY: sold-out bikes are excluded so the rank
  // and Low/Median/High match what Browse shows. A sold-out bike isn't part of the rankings
  // at all — its "How It Compares" card is hidden entirely (see `ranked` below).
  const ranked = isAvailable(model);

  const img = model.colors?.[color]?.image ?? primaryImage(model);
  const cPrices = colorPrices(model, dims);
  const colorUp = upchargeText(cPrices, lowestPrice(model), model.currency, color);
  const productTypes = model.product_types?.length
    ? model.product_types
    : model.product_type
      ? [model.product_type]
      : [];
  const selected = has(model.id);
  // "Other versions" omits sold-out siblings unless the global Sold-out toggle is on
  // (consistent with how sold-out colors / Browse results are hidden).
  const siblings = model.family_id
    ? models.filter((x) => x.family_id === model.family_id && x.id !== model.id
        && (showSoldOut || isAvailable(x)))
    : [];
  const t = model.analysis?.specs_typed ?? {};
  // manufacturer's recommended rider-height range, shown in the active unit
  const ftIn = (inch: number) => `${inToFtIn(inch).ft}'${inToFtIn(inch).in}"`;
  const riderFit =
    t.fit_height_min_in != null && t.fit_height_max_in != null
      ? units === "metric" && t.fit_height_min_mm != null && t.fit_height_max_mm != null
        ? `${Math.round(t.fit_height_min_mm / 10)}–${Math.round(t.fit_height_max_mm / 10)} cm`
        : `${ftIn(t.fit_height_min_in)} – ${ftIn(t.fit_height_max_in)}`
      : null;
  // multi-size models: each frame size with its rider-height range when the
  // brand publishes one (range null -> name-only fallback)
  const frameSizes =
    (model.frame_size_count ?? 0) > 1
      ? (model.frame_sizes ?? [])
          .filter((s): s is typeof s & { size: string } => !!s.size)
          .map((s) => ({
            size: s.size,
            range: s.height_min && s.height_max ? `${s.height_min}–${s.height_max}` : null,
          }))
      : [];
  // per-frame-size breakdown, shown indented under the rider-height entry
  const frameSizeBreakdown =
    frameSizes.length > 0 ? (
      <div>
        <div className="font-medium text-slate-600">Frame Sizes</div>
        <div className="flex flex-col gap-y-0.5 pl-3">
          {frameSizes.map((s) => (
            <div key={s.size} className="whitespace-nowrap">
              <span className="font-medium text-slate-600">{s.size}</span>
              {s.range ? ` ${s.range}` : ""}
            </div>
          ))}
        </div>
      </div>
    ) : null;

  const hasGroup = (g: string) => !!model.specs?.[g] && Object.keys(model.specs[g]).length > 0;
  // these sit under the image (left column) instead of the main spec flow
  // general_info is dropped from display; geometry now renders as a full-width card in
  // the main spec section (last, just before Accessories) rather than in the sidebar.
  const SIDE_GROUPS = ["general_info", "geometry"];   // still excluded from main groups...
  const MAIN_SKIP = ["general_info"];                 // ...but geometry IS shown in main
  // Rider height + frame-size labels live in Key Aspects (with the Frame Sizes
  // breakdown); drop their duplicate copies from Geometry so the cards don't
  // repeat them. Covers rider_height, user_height_range, approx height, inseam,
  // and bike_size/frame_size label rows.
  const isGeoDup = (k: string) =>
    (/rider|user|approx/i.test(k) && /height/i.test(k)) ||
    /height.?range|inseam/i.test(k) ||
    /^(bike|frame)_?sizes?$/i.test(k);
  const sideGroupData = (g: string) => {
    const src = model.specs?.[g] ?? {};
    if (g === "general_info") return riderFit ? { rider_height: riderFit, ...src } : src;
    if (g === "geometry")
      return Object.fromEntries(Object.entries(src).filter(([k]) => !isGeoDup(k)));
    return src;
  };
  // general_info ("Key Aspects") is dropped from display (duplicative — its values live in
  // the "How It Compares" table + rider-fit header); geometry now renders in the main spec
  // section (last card, before Accessories), so the sidebar group list is empty.
  const sideGroups = SIDE_GROUPS.filter(
    (g) => g !== "general_info" && g !== "geometry" && Object.keys(sideGroupData(g)).length > 0);
  const groups = GROUP_ORDER.filter((g) => !MAIN_SKIP.includes(g) && hasGroup(g));
  // Frameset, Wheelset, Brakes and Drivetrain share a single combined card; the
  // card renders at the position of whichever member comes first in GROUP_ORDER.
  const FRAMESET_CARD = ["frameset", "wheelset", "brakes", "drivetrain"];
  const framesetCardGroups = FRAMESET_CARD.filter((g) => groups.includes(g));
  // Sub-sections within the combined card. Frameset is the card body (no
  // sub-heading); Brakes is folded under the Wheelset sub-heading (no heading
  // of its own); Drivetrain keeps its heading.
  const FRAMESET_SUBS: { heading: string | null; groups: string[] }[] = [
    { heading: null, groups: ["frameset"] },
    { heading: "Wheelset", groups: ["wheelset", "brakes"] },
    { heading: "Drivetrain", groups: ["drivetrain"] },
  ];

  // Accessories: the bike's free/bundled items first, then the brand's paid
  // add-ons (deduped against the free list) cheapest first.
  const included = model.included_accessories ?? [];
  const includedNames = new Set(included.map((a) => a.name.toLowerCase()));
  // Model-family matching: an accessory named for ANOTHER of the brand's models
  // (e.g. "Roadster v3 Battery" on a Portola) is hidden; generic/global add-ons
  // (no model name) and this model's own are kept. Family tokens are the model
  // name minus brand/trim words (trailing digits stripped: "Racer1" -> "racer").
  const ACC_STOP = new Set([
    "turbo", "sworks", "works", "specialized", "ride1up", "magician", "the", "and",
    "with", "for", "sl", "comp", "pro", "expert", "evo", "igh", "alloy", "step",
    "through", "thru", "over", "frameset", "carbon", "ltd", "lite", "class", "belt",
    "cvt", "chain", "suspension", "ohlins", "coil", "gen", "edition", "dual", "single",
    "plus", "max", "series", "drt", "evo", "mini",
  ]);
  const famTokens = (name: string): Set<string> => {
    const out = new Set<string>();
    for (let t of (name || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").split(" ")) {
      t = t.replace(/\d+$/, "");
      if (t.length >= 3 && !ACC_STOP.has(t) && !/^\d+$/.test(t)) out.add(t);
    }
    return out;
  };
  const brandFamilies = new Set<string>();
  for (const m of models) {
    if (m.brand === model.brand) for (const t of famTokens(m.model)) brandFamilies.add(t);
  }
  const myFamilies = famTokens(model.model);
  // A "general" accessory is a genuinely universal bolt-on; the brand catalog also lists
  // apparel and niche/other-model items, so we don't treat "no model token" as universal —
  // it must match a known accessory category.
  const UNIVERSAL = /\b(lock|light|headlight|tail.?light|fender|mudguard|bell|horn|mirror|phone|mount|bottle|cage|pump|basket|pannier|bag|kickstand|grip|tire|tyre|tube|charger|lube|net|strap|tool|wrench|helmet|cushion|holder|seat.?post|saddle|key|rack)\b/i;
  const APPAREL = /\b(shirt|tee|jersey|glove|sock|hat|cap|hoodie|beanie|apparel|clothing|shorts?|pants?|jacket|sticker|decal|poster)\b/i;
  // Mine model names from the brand's accessory COMPATIBILITY lists — the part after a
  // spaced " - " ("Fender Set - Sinch / Sinch ST") — so models that AREN'T in our catalog
  // (Sinch, Ramblas, Level) are still recognized as other-models and hidden. Skip
  // colors/sizes (variant suffixes like "- Blue", "- 20\"") and universal words, and only
  // keep tokens that recur (≥2 accessories) so one-off 3rd-party product names don't count.
  // colors / sizes (variant suffixes) + generic accessory-descriptor words, so only real
  // model names get mined (not "Sport Rider Hitch Rack" type product descriptors).
  const VARIANT = new Set(("black white blue red green grey gray silver pink purple orange yellow sand fuchsia matte gloss teal tan brown beige navy inch receiver mips small medium large left right pair color size "
    + "bike ebike hitch sport rider type pin version kit set pack bundle adapter system edition platform support stays replacement part parts cable wire front rear").split(" "));
  const brandAccs = brandByName.get(model.brand)?.available_accessories ?? [];
  const compatFreq = new Map<string, number>();
  for (const a of brandAccs) {
    const compat = (a.name || "").split(/\s[-–]\s/).slice(1).join(" ");
    // raw occurrences (not deduped) so a single accessory that repeats a model with its
    // trims — "… - Ramblas / Ramblas ADV" — still reaches the ≥2 mining threshold.
    for (let t of compat.toLowerCase().replace(/[^a-z0-9]+/g, " ").split(" ")) {
      t = t.replace(/\d+$/, "");
      if (t.length >= 3 && !ACC_STOP.has(t) && !VARIANT.has(t) && !UNIVERSAL.test(t) && !/^\d+$/.test(t))
        compatFreq.set(t, (compatFreq.get(t) ?? 0) + 1);
    }
  }
  const brandModelTokens = new Set<string>(brandFamilies);
  for (const [t, c] of compatFreq) if (c >= 2) brandModelTokens.add(t);
  // Some brands have product LINES that aren't catalog model names: Specialized's
  // "Globe" is its cargo sub-brand (the Haul line) and "Tero" is an eMTB line, so a
  // "Globe Passenger Seat" or "Tero Kickstand" is line-specific, not universal. Map
  // such line words to the catalog family they belong to (globe -> haul) so they're
  // hidden on, e.g., a Vado; an unmapped line (tero, not in the catalog) hides on all.
  const LINE_ALIASES: Record<string, Record<string, string>> = {
    specialized: { globe: "haul", tero: "tero" },
  };
  const aliases = LINE_ALIASES[model.brand] ?? {};
  const accFamilies = (name: string): string[] => {
    const fa = [...famTokens(name)].filter((t) => brandModelTokens.has(t));
    const low = name.toLowerCase();
    for (const [tok, fam] of Object.entries(aliases)) {
      if (new RegExp(`\\b${tok}\\b`).test(low)) fa.push(fam);
    }
    return [...new Set(fa)];
  };
  const appliesToThisModel = (name: string): boolean => {
    if (APPAREL.test(name)) return false;
    const fa = accFamilies(name);
    if (fa.some((t) => myFamilies.has(t))) return true;     // names THIS model -> show
    // Batteries / replacement parts are inherently model-specific; if it didn't match
    // this model above, it's for another (often unlisted) model -> hide.
    const modelSpecific = (/\bbatter/i.test(name) && !/charger/i.test(name))
      || /replacement\s+parts?/i.test(name);
    if (modelSpecific || fa.length) return false;           // other-model part
    return UNIVERSAL.test(name);                            // general only if a known universal
  };
  const paidAccessories = (brandByName.get(model.brand)?.available_accessories ?? [])
    .filter((a) => !a.free && a.price != null && !includedNames.has(a.name.toLowerCase())
      && appliesToThisModel(a.name))
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0));

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <button onClick={goBack} className="text-sm text-brand-600 hover:underline">← Back</button>

      {/* Mobile is a single flex column; each desktop column wrapper is display:contents
          on mobile so its children join the parent flex and can be ordered individually:
          image (1) → product header (2) → Key Aspects/Geometry (3) → extras (4). Desktop
          (lg) restores the two independent-flowing columns. */}
      <div className="mt-3 flex flex-col gap-4 lg:grid lg:grid-cols-2 lg:items-start lg:gap-6">
        {/* no overflow-hidden on the card: the swatch hover tooltips must be
            able to escape; the image wrapper rounds and clips itself instead.
            The overlays anchor to this inner relative wrapper (which hugs the
            image), NOT the card — the grid stretches the card taller than the
            image, which would push a card-anchored pill below the photo. */}
        <div className="contents lg:flex lg:flex-col lg:gap-4">
          <div className="order-1 lg:order-none">
        <div className="card border-slate-100">
          <div className="relative">
            <div className="aspect-[4/3] w-full overflow-hidden rounded-xl bg-slate-100">
              {img ? (
                <img
                  src={img}
                  alt={`${model.model} — ${model.colors?.[color]?.name ?? ""}`}
                  className="h-full w-full object-contain"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-slate-300">no image</div>
              )}
            </div>
            {/* color choice overlays the image's top-left corner, above the photo
                and inset so it never crosses the card border */}
            {model.colors && model.colors.length > 0 && (
              <div className="absolute left-3 top-3 z-10 rounded-full bg-white/75 px-2.5 py-2 shadow-sm backdrop-blur-sm">
                <ColorSwatches
                  colors={model.colors}
                  selected={color}
                  onSelect={setColor}
                  size="h-6 w-6"
                  prices={cPrices}
                  basePrice={lowestPrice(model)}
                  currency={model.currency}
                  showLabel={false}
                  hidden={hiddenColors}
                />
              </div>
            )}
            {/* current color, on top of the bottom middle of the image; when a hex
                is known the name is shown in that colour on a contrasting chip */}
            {model.colors?.[color]?.name && (() => {
              const chip = colorChipStyle(model.colors[color].hex);
              return (
                <div
                  className={`pointer-events-none absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 truncate rounded-full border px-3 py-1 text-sm shadow-sm ${chip ? "" : "border-slate-300 bg-white/75 text-slate-600 backdrop-blur-sm"}`}
                  style={chip ? { color: chip.color, borderColor: chip.color } : undefined}
                >
                  {model.colors[color].name}
                  {colorUp && <span className="font-semibold text-rose-600">{colorUp}</span>}
                </div>
              );
            })()}
          </div>
        </div>
          </div>
          <div className="order-3 lg:order-none space-y-4">
        {/* Value score + the coarse "why": build tier (quality) and the typical price for
            that tier/type vs. this bike's price. The premium components stay in Highlights. */}
        {model.analysis?.specs_typed?.build_tier && (
          <div className="space-y-2 rounded-xl border border-slate-200 p-3">
            {model.analysis.specs_typed.value_level && (
              <div className="flex flex-wrap items-center gap-2">
                <ValuePips level={model.analysis.specs_typed.value_level} />
                <span className="text-sm font-semibold text-slate-700">
                  {model.analysis.specs_typed.value_level} value
                </span>
              </div>
            )}
            <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-slate-500">
              <BuildGrade model={model} />
              {model.analysis.specs_typed.value_typical != null && model.price != null && (
                <span>
                  · similar ≈ {formatPrice(model.analysis.specs_typed.value_typical, model.currency)} ·
                  this bike {formatPrice(model.price, model.currency)}
                  {model.analysis.specs_typed.value_extras
                    ? ` (incl. ~${formatPrice(model.analysis.specs_typed.value_extras, model.currency)} extras)`
                    : ""}
                </span>
              )}
            </div>
            {model.analysis.specs_typed.value_level &&
              model.analysis.specs_typed.value_index != null &&
              (() => {
                const t = model.analysis!.specs_typed;
                const idx = t.value_index!;
                const below = Math.round((1 - 1 / idx) * 100);
                const markers = t.build_markers ?? [];
                return (
                  <details className="text-xs text-slate-500">
                    <summary className="cursor-pointer select-none font-medium text-slate-600 hover:text-slate-800">
                      How this value was scored
                    </summary>
                    <ol className="mt-1.5 list-decimal space-y-1 pl-4 marker:text-slate-400">
                      <li>
                        Build grade <span className="font-semibold text-slate-700">{t.build_tier}</span>
                        {markers.length ? ` — ${markers.join(", ")}` : ""}.
                      </li>
                      <li>
                        Ranked against <span className="font-semibold text-slate-700">{t.value_peers}</span>{" "}
                        {t.build_tier}-tier {model.product_type} bikes (typical ≈{" "}
                        {formatPrice(t.value_typical, model.currency)}).
                      </li>
                      <li>
                        Priced {formatPrice(model.price, model.currency)}
                        {t.value_extras ? ` (−${formatPrice(t.value_extras, model.currency)} extras)` : ""} →{" "}
                        <span className="font-semibold text-slate-700">{idx.toFixed(2)}×</span> (
                        {Math.abs(below)}% {below >= 0 ? "below" : "above"} typical).
                      </li>
                      <li>
                        <span className="font-semibold text-slate-700">{t.value_level}</span>
                        {t.value_next
                          ? `. For ${t.value_next.label} it would need to be ≤ ${formatPrice(
                              t.value_next.price,
                              model.currency,
                            )}.`
                          : " — the top band."}
                      </li>
                    </ol>
                  </details>
                );
              })()}
          </div>
        )}
        {sideGroups.map((g) => {
          const isGeneral = g === "general_info";
          // "Key Aspects" leads with the rider-height fit range; Geometry has the
          // duplicate rider-height stripped (see sideGroupData)
          const groupData = sideGroupData(g);
          // Geometry usually differs per frame size; render it as a per-size table
          // (attribute rows × size columns) when the bike has named sizes.
          const sizeLabels = frameSizes.map((s) => s.size);
          const geoTable =
            g === "geometry" && sizeLabels.length > 1 ? (
              <GeometryTable geo={groupData} sizes={sizeLabels} />
            ) : null;
          if (g === "geometry" && sizeLabels.length > 1 && !geoTableHasRows(groupData, sizeLabels))
            return null;
          return (
            <div key={g} className="card p-4">
              <h2 className="mb-2 font-bold uppercase tracking-wide text-slate-800">
                {isGeneral ? "Key Aspects" : groupLabel(g)}
              </h2>
              {geoTable ?? (
                <SpecTable
                  group={groupData}
                  emphasize
                  subRows={isGeneral && frameSizeBreakdown ? { rider_height: frameSizeBreakdown } : undefined}
                />
              )}
            </div>
          );
        })}
          </div>
        </div>

        {/* RIGHT desktop column: product header + extras (contents on mobile) */}
        <div className="contents lg:flex lg:flex-col lg:gap-4">
          <div className="order-2 lg:order-none space-y-4">
          <div>
            {/* brand name links to the brand's product page (same target as "View at …") */}
            <div className="text-sm font-medium uppercase tracking-wide text-brand-600">
              <AffiliateLink
                brand={model.brand}
                url={model.url}
                showBadge={false}
                className="hover:text-brand-700 hover:underline"
              >
                {model.brand}
              </AffiliateLink>
            </div>
            <h1 className="text-2xl font-bold text-slate-900">
              {displayName(model)}
              {model.tier && (
                <span className="chip ml-2 bg-amber-100 align-middle text-amber-800">{model.tier}</span>
              )}
            </h1>
            <VariantPicker
              model={model}
              colorName={model.colors?.[color]?.name}
              dims={dims}
              onChange={setDims}
              basePrice={lowestPrice(model)}
            />
            {productTypes.length > 0 && (
              <div className="mt-1.5 text-sm text-slate-500">{productTypes.join(" · ")}</div>
            )}
            {/* standouts vs same-type peers — same star-list format as the card,
                left-aligned with the title/price */}
            <div className="mt-3">
              <HighlightsList standouts={model.analysis?.standouts} />
            </div>
          </div>

          {/* items-end so the Free shipping (and warranty) chip's bottom aligns to the
              bottom of the large price, rather than centering against it. */}
          <div className="flex flex-wrap items-end gap-3">
            <Price
              model={model}
              size="lg"
              price={variantPrice(model, model.colors?.[color]?.name, dims)}
              soldOut={model.availability?.status === "sold_out" || colorSoldOut(model, color)}
            />
            {model.warranty && <span className="chip">{model.warranty}</span>}
            {model.shipping_free && <span className="chip bg-emerald-50 text-emerald-700">Free shipping</span>}
          </div>

          {/* frame sizes show even when the brand publishes no rider-height
              range (e.g. some Cannondale dealer-only models) */}
          {(riderFit || frameSizes.length > 0) && (
            <div className="text-sm text-slate-600">
              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                <RiderHeightIcon className="h-5 w-5" />
                {riderFit ? (
                  <>
                    <span className="font-medium text-slate-700">Fits riders</span> {riderFit}
                  </>
                ) : (
                  <>
                    <span className="font-medium text-slate-700">Frame sizes</span>{" "}
                    <span className="text-slate-400">
                      {frameSizes.map((s) => s.size).join(", ")}
                    </span>
                  </>
                )}
              </div>
            </div>
          )}

          {/* partial stock: list the option values that are unavailable */}
          {model.availability?.status === "in_stock" &&
            Object.keys(model.availability.sold_out_options).length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <span className="font-semibold">Some options are sold out:</span>{" "}
                {Object.entries(model.availability.sold_out_options)
                  .map(([axis, vals]) => `${axis} — ${vals.join(", ")}`)
                  .join("; ")}
              </div>
            )}

          <div className="flex flex-wrap gap-2">
            <AffiliateLink brand={model.brand} url={model.url} className="btn-primary">
              View at {titleCase(model.brand)} →
            </AffiliateLink>
            <button
              type="button"
              onClick={() => toggle(model.id)}
              disabled={!selected && isFull}
              className={selected ? "btn-primary" : "btn-ghost"}
            >
              {selected ? "✓ Comparing" : "Add to compare"}
            </button>
          </div>
          </div>
          <div className="order-4 lg:order-none space-y-4">

          {siblings.length > 0 && (
            <div className="card p-4">
              <h3 className="mb-2 font-bold uppercase tracking-wide text-slate-800">Other versions of this bike</h3>
              <ul className="space-y-1.5">
                {siblings.map((s) => (
                  <li key={s.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <Link
                      to={`/bike/${encodeURIComponent(s.id)}`}
                      replace
                      className="font-medium text-brand-700 hover:underline"
                    >
                      {s.tier ?? s.model}
                    </Link>
                    <span className="text-slate-500">{formatPrice(s.price ?? s.price_min, s.currency)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <SpecialFeaturesCard features={model.analysis.uncommon_features} />
          </div>
        </div>
      </div>

      {/* percentile context — a table vs the bike's same-type cohort: min / median /
          max, this bike's value, and its signed difference from the median (green when
          on the "better" side for that metric, red when worse). */}
      {ranked && (
      <section className="mt-6 card p-4">
        <h2 className="mb-4 text-lg font-bold tracking-wide text-slate-800">{compareHeading}</h2>
        <HowItCompares model={model} models={models} units={units} compact />
        <HowItComparesLegend />
      </section>
      )}

      {/* grouped specs — single column so the section order reads top-to-bottom */}
      <section className="mt-6 grid gap-4">
        {groups.map((g) => {
          if (FRAMESET_CARD.includes(g)) {
            // render the shared card once, at the first present member's slot
            if (g !== framesetCardGroups[0]) return null;
            return (
              <div key="frameset-card" className="card p-4">
                <h2 className="mb-2 font-bold uppercase tracking-wide text-slate-800">Frameset</h2>
                {FRAMESET_SUBS.map((sub, i) => {
                  const present = sub.groups.filter((cg) => groups.includes(cg));
                  if (!present.length) return null;
                  return (
                    <div key={sub.heading ?? present[0]} className={i > 0 ? "mt-4" : undefined}>
                      {sub.heading && (
                        <h3 className="mb-2 font-bold uppercase tracking-wide text-slate-800">{sub.heading}</h3>
                      )}
                      {present.map((cg) => (
                        <SpecTable key={cg} group={model.specs[cg]} emphasize hideCaptured />
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          }
          if (g === "geometry") {
            // rider-height / frame-size dups stripped; per-size table when multi-size.
            const geoData = sideGroupData("geometry");
            const sizeLabels = frameSizes.map((s) => s.size);
            const useTable = sizeLabels.length > 1;
            if (useTable ? !geoTableHasRows(geoData, sizeLabels) : !Object.keys(geoData).length)
              return null;
            return (
              <div key={g} className="card p-4">
                <h2 className="mb-2 font-bold uppercase tracking-wide text-slate-800">Geometry</h2>
                {useTable
                  ? <GeometryTable geo={geoData} sizes={sizeLabels} />
                  : <SpecTable group={geoData} emphasize />}
              </div>
            );
          }
          return (
            <div key={g} className="card p-4">
              <h2 className="mb-2 font-bold uppercase tracking-wide text-slate-800">{groupLabel(g)}</h2>
              <SpecTable group={model.specs[g]} emphasize hideCaptured />
            </div>
          );
        })}

        {(included.length > 0 || paidAccessories.length > 0) && (
          <div className="card p-4">
            <h2 className="mb-2 font-bold uppercase tracking-wide text-slate-800">Accessories</h2>
            <ul className="space-y-1.5 text-sm">
              {included.map((a) => (
                <li key={`inc-${a.name}`} className="flex items-baseline justify-between gap-3">
                  <span className="text-slate-700">{a.name}</span>
                  <span className="shrink-0 font-medium text-emerald-600">Included</span>
                </li>
              ))}
              {(allAccessories ? paidAccessories : paidAccessories.slice(0, 10)).map((a, i) => (
                <li key={`add-${a.name}-${i}`} className="flex items-baseline justify-between gap-3">
                  {a.url ? (
                    <AffiliateLink brand={model.brand} url={a.url} showBadge={false} className="truncate text-brand-600 underline decoration-brand-300 underline-offset-2 hover:text-brand-700 hover:decoration-brand-600">
                      {a.name}
                    </AffiliateLink>
                  ) : (
                    <span className="truncate text-slate-700">{a.name}</span>
                  )}
                  {a.on_sale && a.regular_price != null && a.price != null ? (
                    <span className="inline-flex shrink-0 items-baseline gap-1.5 tabular-nums">
                      <span className="text-slate-400 line-through">{formatPrice(a.regular_price, model.currency)}</span>
                      <span className="font-medium text-rose-600">{formatPrice(a.price, model.currency)}</span>
                      <span className="text-xs font-semibold text-rose-700">
                        -{Math.round(((a.regular_price - a.price) / a.regular_price) * 100)}%
                      </span>
                    </span>
                  ) : (
                    <span className="shrink-0 tabular-nums text-slate-500">{formatPrice(a.price, model.currency)}</span>
                  )}
                </li>
              ))}
            </ul>
            {paidAccessories.length > 10 && (
              <button
                type="button"
                onClick={() => setAllAccessories(!allAccessories)}
                className="mt-2 text-xs text-brand-600 hover:underline"
              >
                {allAccessories ? "Show less" : `Show all (${paidAccessories.length})`}
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">{children}</div>;
}
