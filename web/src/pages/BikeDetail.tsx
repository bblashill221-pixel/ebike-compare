import { Link, useParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare } from "../compare/CompareContext";
import { formatPrice, titleCase } from "../format";
import { ScorePanel } from "../components/ScorePanel";
import { SpecTable } from "../components/SpecTable";
import { DistributionPlot } from "../components/DistributionPlot";
import { AffiliateLink } from "../components/AffiliateLink";
import { primaryImage } from "../components/BikeCard";

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

const PERCENTILE_FIELDS: { field: string; label: string; unit?: string; typed?: string }[] = [
  { field: "price", label: "Price", unit: "$" },
  { field: "battery_wh", label: "Battery", unit: " Wh" },
  { field: "motor_w", label: "Motor", unit: " W" },
  { field: "torque_nm", label: "Torque", unit: " Nm" },
  { field: "range_mi", label: "Range", unit: " mi" },
  { field: "weight_lb", label: "Weight", unit: " lb" },
];

export function BikeDetail() {
  const { id } = useParams();
  const { byId, analysisStats, status } = useData();
  const { has, toggle, isFull } = useCompare();

  if (status === "loading") return <Center>Loading…</Center>;
  const model = id ? byId.get(decodeURIComponent(id)) : undefined;
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

  const img = primaryImage(model);
  const selected = has(model.id);
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
              <img src={img} alt={model.model} className="h-full w-full object-contain" />
            ) : (
              <div className="flex h-full items-center justify-center text-slate-300">no image</div>
            )}
          </div>
          {model.colors && model.colors.length > 0 && (
            <div className="flex flex-wrap gap-2 p-4">
              {model.colors.map((c) => (
                <span key={c.name} className="chip">
                  {c.hex && (
                    <span className="h-3 w-3 rounded-full border border-slate-300" style={{ background: c.hex }} />
                  )}
                  {c.name}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-4">
          <div>
            <div className="text-sm font-medium uppercase tracking-wide text-brand-600">{model.brand}</div>
            <h1 className="text-2xl font-bold text-slate-900">{model.model}</h1>
            {model.product_type && <div className="text-sm text-slate-500">{model.product_type}</div>}
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <span className="text-2xl font-bold">{formatPrice(model.price ?? model.price_min, model.currency)}</span>
            {model.pricing?.on_sale && <span className="chip bg-rose-100 text-rose-700">On sale</span>}
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

          <div className="card p-4">
            <ScorePanel analysis={model.analysis} />
          </div>
        </div>
      </div>

      {/* percentile context */}
      <section className="mt-6 card p-4">
        <h2 className="mb-3 font-semibold text-slate-800">How it compares to the fleet</h2>
        <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
          {PERCENTILE_FIELDS.map(({ field, label, unit }) => {
            const stat = analysisStats[field];
            const v = valueOf(field);
            if (!stat) return null;
            return (
              <div key={field}>
                <div className="mb-1 flex justify-between text-sm">
                  <span className="font-medium text-slate-700">{label}</span>
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
