import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

// DEV-ONLY QA page: renders data/current/anomalies.json (audit_anomalies.py) — a
// ranked triage list of likely-misclassified / misparsed bikes. The route is
// registered only when import.meta.env.DEV, and anomalies.json is copied into
// public/ only by `predev` (never bundled into production), so this never ships.

type Anomaly = {
  id: string;
  brand: string;
  model: string;
  url: string;
  rule: string;
  severity: "high" | "medium" | "low";
  detail: string;
};
type Report = {
  generated_at: string;
  model_count: number;
  anomaly_count: number;
  by_severity: Record<string, number>;
  by_rule: Record<string, number>;
  anomalies: Anomaly[];
};

const SEV_STYLE: Record<string, string> = {
  high: "bg-rose-100 text-rose-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

export function QaAnomalies() {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string>();
  const [rule, setRule] = useState<string>("all");

  useEffect(() => {
    const base = import.meta.env.BASE_URL || "/";
    fetch(`${base}anomalies.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setReport)
      .catch((e) => setError(String(e)));
  }, []);

  if (error)
    return (
      <Wrap>
        <p className="text-sm text-slate-500">
          Couldn’t load <code>anomalies.json</code> ({error}). Run{" "}
          <code>python audit_anomalies.py</code> then restart <code>npm run dev</code>.
        </p>
      </Wrap>
    );
  if (!report) return <Wrap><p className="text-sm text-slate-500">Loading…</p></Wrap>;

  const rules = ["all", ...Object.keys(report.by_rule)];
  const rows = report.anomalies.filter((a) => rule === "all" || a.rule === rule);

  return (
    <Wrap>
      <div className="mb-1 flex items-baseline gap-2">
        <h1 className="text-xl font-bold text-slate-900">QA · Anomalies</h1>
        <span className="rounded bg-rose-600 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-white">
          Dev only
        </span>
      </div>
      <p className="mb-4 text-sm text-slate-500">
        {report.anomaly_count} flags across {report.model_count} bikes · high{" "}
        {report.by_severity.high ?? 0} / medium {report.by_severity.medium ?? 0} / low{" "}
        {report.by_severity.low ?? 0} ·{" "}
        <span className="text-slate-400">
          generated {new Date(report.generated_at).toLocaleString()}
        </span>
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        {rules.map((r) => (
          <button
            key={r}
            type="button"
            onClick={() => setRule(r)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              rule === r ? "border-brand-600 bg-brand-50 text-brand-700" : "border-slate-300 text-slate-600"
            }`}
          >
            {r}
            {r !== "all" && <span className="ml-1 text-slate-400">{report.by_rule[r]}</span>}
          </button>
        ))}
      </div>

      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 text-left text-xs uppercase text-slate-400">
            <th className="py-1.5 pr-3">Severity</th>
            <th className="py-1.5 pr-3">Rule</th>
            <th className="py-1.5 pr-3">Bike</th>
            <th className="py-1.5">Detail</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((a, i) => (
            <tr key={`${a.id}-${a.rule}-${i}`} className="align-top">
              <td className="py-1.5 pr-3">
                <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${SEV_STYLE[a.severity]}`}>
                  {a.severity}
                </span>
              </td>
              <td className="py-1.5 pr-3 font-mono text-xs text-slate-600">{a.rule}</td>
              <td className="py-1.5 pr-3">
                <Link to={`/bike/${a.id}`} className="font-medium text-brand-600 hover:underline">
                  {a.model}
                </Link>
                <span className="ml-1 text-xs text-slate-400">{a.brand}</span>
              </td>
              <td className="py-1.5 text-slate-700">{a.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <p className="mt-4 text-sm text-slate-500">No anomalies for this rule. 🎉</p>}
    </Wrap>
  );
}

function Wrap({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-5xl px-4 py-6">{children}</div>;
}
