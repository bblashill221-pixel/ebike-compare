import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { ColorSwatches } from "../components/ColorSwatches";
import { useCompare } from "../compare/CompareContext";
import { formatPrice, titleCase } from "../format";
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
  "included_accessories",
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
  const { byId, models, analysisStats, status } = useData();
  const { has, toggle, isFull } = useCompare();
  const model = id ? byId.get(decodeURIComponent(id)) : undefined;
  // first listed color is the default; selection drives the photo
  const [color, setColor] = useState(0);
  useEffect(() => setColor(0), [model?.id]);

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
  const selected = has(model.id);
  const siblings = model.family_id
    ? models.filter((x) => x.family_id === model.family_id && x.id !== model.id)
    : [];
  const t = model.analysis?.specs_typed ?? {};
  const valueOf = (field: string) =>
    field === "price" ? model.price ?? model.price_min : (t[field] as number | undefined);

  const groups = GROUP_ORDER.filter((g) => model.specs?.[g] && Object.keys(model.specs[g]).length);

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <Link to="/" className="text-sm text-brand-600 hover:underline">← Back to browse</Link>

      <div className="mt-3 grid gap-6 lg:grid-cols-2">
        <div className="card overflow-hidden">
          <div className="aspect-[4/3] w-full bg-slate-100">
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
            {model.colors && model.colors.length > 0 && (
              <div className="mt-2">
                <ColorSwatches colors={model.colors} selected={color} onSelect={setColor} size="h-6 w-6" />
              </div>
            )}
            {model.product_type && <div className="mt-1.5 text-sm text-slate-500">{model.product_type}</div>}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Price model={model} size="lg" />
            {model.warranty && <span className="chip">{model.warranty}</span>}
            {model.shipping_free && <span className="chip bg-emerald-50 text-emerald-700">Free shipping</span>}
          </div>

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
                  <span className="text-slate-500">{v != null ? `${v}${unit ?? ""}` : "—"}</span>
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
      </section>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">{children}</div>;
}
