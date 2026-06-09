import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { ColorSwatches, upchargeText } from "../components/ColorSwatches";
import { useColorSelection, defaultColorIndex, colorSoldOut, soldOutColors } from "../colorSelection";
import { useShowSoldOut } from "../soldOut";
import { useCompare } from "../compare/CompareContext";
import { formatPrice, titleCase } from "../format";
import { colorPrices, defaultDims, lowestPrice, variantPrice } from "../pricing";
import { VariantPicker } from "../components/VariantPicker";
import { Price } from "../components/Price";
import { ScorePanel } from "../components/ScorePanel";
import { SpecTable } from "../components/SpecTable";
import { DistributionPlot } from "../components/DistributionPlot";
import { AffiliateLink } from "../components/AffiliateLink";
import { displayName, primaryImage } from "../components/BikeCard";
import { BatteryIcon, MotorIcon, RangeIcon, TorqueIcon, WeightIcon } from "../components/icons";

const GROUP_ORDER = [
  "general_info",
  "ebike_system",
  "safety",
  "certifications",
  "water_resistance",
  "frameset",
  "drivetrain",
  "brakes",
  "wheelset",
  "cockpit",
  "geometry",
  // NB included_accessories is deliberately not a spec group here — the
  // dedicated Accessories card below renders it (free first, then the brand's
  // paid add-ons with prices).
];

const PERCENTILE_FIELDS: {
  field: string;
  label: string;
  unit?: string;
  icon?: React.ReactNode;
}[] = [
  { field: "price", label: "Price", unit: "$" },
  { field: "battery_wh", label: "Battery", unit: " Wh", icon: <BatteryIcon /> },
  { field: "motor_w", label: "Motor", unit: " W", icon: <MotorIcon /> },
  { field: "torque_nm", label: "Torque", unit: " Nm", icon: <TorqueIcon /> },
  { field: "range_mi", label: "Range", unit: " mi", icon: <RangeIcon /> },
  { field: "weight_lb", label: "Weight", unit: " lb", icon: <WeightIcon /> },
];

export function BikeDetail() {
  const { id } = useParams();
  const { byId, models, analysisStats, brandByName, status } = useData();
  const { has, toggle, isFull } = useCompare();
  const model = id ? byId.get(decodeURIComponent(id)) : undefined;
  // selection is shared with the browse cards (and persists for the session);
  // a fresh visit defaults to the first in-stock colorway
  const [showSoldOut] = useShowSoldOut();
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
          <p className="mb-3">That e-bike could not be found.</p>
          <Link to="/" className="btn-primary">Back to browse</Link>
        </div>
      </Center>
    );
  }

  const img = model.colors?.[color]?.image ?? primaryImage(model);
  const cPrices = colorPrices(model, dims);
  const colorUp = upchargeText(cPrices, lowestPrice(model), model.currency, color);
  const productTypes = model.product_types?.length
    ? model.product_types
    : model.product_type
      ? [model.product_type]
      : [];
  const selected = has(model.id);
  const siblings = model.family_id
    ? models.filter((x) => x.family_id === model.family_id && x.id !== model.id)
    : [];
  const t = model.analysis?.specs_typed ?? {};
  const valueOf = (field: string) =>
    field === "price" ? model.price ?? model.price_min : (t[field] as number | undefined);

  const groups = GROUP_ORDER.filter((g) => model.specs?.[g] && Object.keys(model.specs[g]).length);

  // Accessories: the bike's free/bundled items first, then the brand's paid
  // add-ons (deduped against the free list) cheapest first.
  const included = model.included_accessories ?? [];
  const includedNames = new Set(included.map((a) => a.name.toLowerCase()));
  const paidAccessories = (brandByName.get(model.brand)?.available_accessories ?? [])
    .filter((a) => !a.free && a.price != null && !includedNames.has(a.name.toLowerCase()))
    .sort((a, b) => (a.price ?? 0) - (b.price ?? 0));

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Link to="/" className="text-sm text-brand-600 hover:underline">← Back to browse</Link>

      <div className="mt-3 grid gap-6 lg:grid-cols-2">
        {/* no overflow-hidden on the card: the swatch hover tooltips must be
            able to escape; the image wrapper rounds and clips itself instead.
            The overlays anchor to this inner relative wrapper (which hugs the
            image), NOT the card — the grid stretches the card taller than the
            image, which would push a card-anchored pill below the photo. */}
        <div className="card">
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
            {/* color choice overlays the image's top-left corner */}
            {model.colors && model.colors.length > 0 && (
              <div className="absolute left-3 top-3 rounded-full bg-white/75 px-2.5 py-2 shadow-sm backdrop-blur-sm">
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
            {/* current color, on top of the bottom middle of the image */}
            {model.colors?.[color]?.name && (
              <div className="pointer-events-none absolute bottom-3 left-1/2 max-w-[90%] -translate-x-1/2 truncate rounded-full bg-white/75 px-3 py-1 text-sm text-slate-600 shadow-sm backdrop-blur-sm">
                [{model.colors[color].name}
                {colorUp && <span className="font-semibold text-rose-600">{colorUp}</span>}]
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-sm font-medium uppercase tracking-wide text-brand-600">{model.brand}</div>
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
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Price
              model={model}
              size="lg"
              price={variantPrice(model, model.colors?.[color]?.name, dims)}
              soldOut={model.availability?.status === "sold_out" || colorSoldOut(model, color)}
            />
            {model.warranty && <span className="chip">{model.warranty}</span>}
            {model.shipping_free && <span className="chip bg-emerald-50 text-emerald-700">Free shipping</span>}
          </div>

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

          {siblings.length > 0 && (
            <div className="card p-4">
              <h3 className="mb-2 font-semibold text-slate-800">Other versions of this bike</h3>
              <ul className="space-y-1.5">
                {siblings.map((s) => (
                  <li key={s.id} className="flex items-baseline justify-between gap-3 text-sm">
                    <Link
                      to={`/bike/${encodeURIComponent(s.id)}`}
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

          <div className="card p-4">
            <ScorePanel analysis={model.analysis} />
          </div>
        </div>
      </div>

      {/* percentile context */}
      <section className="mt-6 card p-4">
        <h2 className="mb-3 font-semibold text-slate-800">How it compares to the fleet</h2>
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {PERCENTILE_FIELDS.map(({ field, label, unit, icon }) => {
            const stat = analysisStats[field];
            const v = valueOf(field);
            if (!stat) return null;
            return (
              <div key={field}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="flex items-center gap-1.5 font-medium text-slate-700">
                    {icon}
                    {label}
                  </span>
                  <span className="text-slate-500">
                    {v == null ? "—" : unit === "$" ? `$${v}` : `${v}${unit ?? ""}`}
                  </span>
                </div>
                <DistributionPlot stat={stat} value={v} unit={unit} />
              </div>
            );
          })}
        </div>
      </section>

      {/* grouped specs */}
      <section className="mt-6 grid gap-4 md:grid-cols-2">
        {groups.map((g) => (
          <div key={g} className="card p-4">
            <h2 className="mb-2 font-semibold text-slate-800">{titleCase(g)}</h2>
            <SpecTable group={model.specs[g]} />
          </div>
        ))}

        {(included.length > 0 || paidAccessories.length > 0) && (
          <div className="card p-4">
            <h2 className="mb-2 font-semibold text-slate-800">Accessories</h2>
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
                    <AffiliateLink brand={model.brand} url={a.url} showBadge={false} className="truncate text-slate-700 hover:text-brand-700 hover:underline">
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
