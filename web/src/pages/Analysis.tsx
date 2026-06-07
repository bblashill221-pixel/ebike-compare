import { useData } from "../data/DataProvider";
import { DistributionPlot } from "../components/DistributionPlot";
import { formatNumber, formatPrice } from "../format";

const FIELD_META: Record<string, { label: string; unit?: string; price?: boolean }> = {
  price: { label: "Price", price: true },
  battery_wh: { label: "Battery", unit: " Wh" },
  motor_w: { label: "Motor (nominal)", unit: " W" },
  motor_peak_w: { label: "Motor (peak)", unit: " W" },
  torque_nm: { label: "Torque", unit: " Nm" },
  range_mi: { label: "Range", unit: " mi" },
  weight_lb: { label: "Weight", unit: " lb" },
  gears: { label: "Gears" },
  bom_pct: { label: "Est. component cost (% of retail)" },
};

const ORDER = ["price", "battery_wh", "motor_w", "motor_peak_w", "torque_nm", "range_mi", "weight_lb", "gears", "bom_pct"];

export function Analysis() {
  const { analysisStats, disclaimer, models, status } = useData();
  if (status === "loading") return <Center>Loading…</Center>;

  const fields = ORDER.filter((f) => analysisStats[f]);

  const fmt = (f: string, v: number) => {
    const meta = FIELD_META[f];
    if (meta?.price) return formatPrice(v);
    if (f === "bom_pct") return `${Math.round(v * 100)}%`;
    return `${formatNumber(v, 1)}${meta?.unit ?? ""}`;
  };

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="text-xl font-bold text-slate-900">Fleet analysis</h1>
      <p className="mt-1 max-w-3xl text-sm text-slate-500">
        Where each spec sits across the {models.length} bikes we track. Bands show the 10th–90th
        percentile; the line is the median. These are comparison aids — there is no overall ranking.
      </p>

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        {fields.map((f) => {
          const s = analysisStats[f];
          const meta = FIELD_META[f];
          return (
            <div key={f} className="card p-4">
              <div className="mb-2 flex items-baseline justify-between">
                <h2 className="font-semibold text-slate-800">{meta?.label ?? f}</h2>
                <span className="text-xs text-slate-400">{s.count} bikes</span>
              </div>
              <DistributionPlot stat={s} />
              <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
                <Stat label="low (p10)" value={fmt(f, s.p10)} />
                <Stat label="median" value={fmt(f, s.p50)} />
                <Stat label="high (p90)" value={fmt(f, s.p90)} />
              </div>
            </div>
          );
        })}
      </div>

      {disclaimer && (
        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">
          <strong className="font-medium text-slate-600">Methodology:</strong> {disclaimer}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-semibold text-slate-800">{value}</div>
      <div className="text-slate-400">{label}</div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center text-slate-500">{children}</div>;
}
