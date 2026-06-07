import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare } from "../compare/CompareContext";
import type { Model } from "../types";
import { titleCase } from "../format";
import { Price } from "../components/Price";
import { SCORE_ORDER } from "../components/ScoreBars";
import { CompareTable } from "../components/CompareTable";
import { AffiliateLink } from "../components/AffiliateLink";
import { primaryImage } from "../components/BikeCard";

export function Compare() {
  const { byId, status } = useData();
  const { ids: trayIds, toggle } = useCompare();
  const [params] = useSearchParams();

  // Seed the compare tray from ?ids= on first load (shareable URLs).
  const urlIds = (params.get("ids") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  useEffect(() => {
    if (urlIds.length) {
      urlIds.forEach((id) => {
        if (!trayIds.includes(id)) toggle(id);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "loading") {
    return <Center>Loading…</Center>;
  }

  const ids = (trayIds.length ? trayIds : urlIds).slice(0, 4);
  const models = ids.map((id) => byId.get(id)).filter((m): m is Model => !!m);

  if (models.length < 2) {
    return (
      <Center>
        <div className="max-w-md text-center">
          <p className="mb-3 text-slate-600">
            Add at least two e-bikes to compare. Browse and tap <strong>Compare</strong> on the bikes you’re weighing.
          </p>
          <Link to="/" className="btn-primary">Browse e-bikes</Link>
        </div>
      </Center>
    );
  }

  const cols = `minmax(8rem,10rem) repeat(${models.length}, minmax(0,1fr))`;

  return (
    <div className="mx-auto max-w-7xl px-4 py-6">
      <h1 className="mb-4 text-xl font-bold text-slate-900">Compare {models.length} e-bikes</h1>

      {/* header + scores */}
      <div className="card mb-6 overflow-x-auto">
        <div className="min-w-[40rem]">
          {/* model headers */}
          <div className="grid border-b border-slate-100" style={{ gridTemplateColumns: cols }}>
            <div className="p-3" />
            {models.map((m) => (
              <div key={m.id} className="border-l border-slate-100 p-3">
                {primaryImage(m) ? (
                  <img src={primaryImage(m)!} alt="" className="mb-2 h-20 w-full object-contain" />
                ) : null}
                <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{m.brand}</div>
                <Link to={`/bike/${encodeURIComponent(m.id)}`} className="font-semibold text-slate-900 hover:text-brand-700">
                  {m.model}
                </Link>
                <div className="mt-1"><Price model={m} /></div>
                <div className="mt-2 flex flex-col gap-1">
                  <AffiliateLink brand={m.brand} url={m.url} className="text-sm font-medium text-brand-700 hover:underline">
                    View at {titleCase(m.brand)} →
                  </AffiliateLink>
                  <button type="button" onClick={() => toggle(m.id)} className="text-left text-xs text-slate-400 hover:text-rose-600">
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
          {/* per-dimension scores */}
          {SCORE_ORDER.filter((k) => models.some((m) => k in (m.analysis?.scores ?? {}))).map((k) => {
            const vals = models.map((m) => m.analysis?.scores?.[k]);
            const best = Math.max(...vals.map((v) => v ?? -1));
            return (
              <div key={k} className="grid border-b border-slate-50" style={{ gridTemplateColumns: cols }}>
                <div className="bg-slate-50/50 p-2 text-sm font-medium text-slate-500">{titleCase(k)}</div>
                {vals.map((v, i) => (
                  <div key={i} className="border-l border-slate-100 p-2">
                    <div className="flex items-center gap-2">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.max(0, Math.min(100, v ?? 0))}%` }} />
                      </div>
                      <span className={`w-7 text-right text-xs tabular-nums ${v != null && v === best && best > 0 ? "font-bold text-emerald-600" : "text-slate-500"}`}>
                        {v != null ? Math.round(v) : "—"}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      <p className="mb-4 text-xs text-slate-400">
        Scores are independent comparison aids (0–100); the best in each row is highlighted. There is no overall winner — compare on what matters to you. Differing spec rows below are shaded.
      </p>

      <div className="overflow-x-auto">
        <div className="min-w-[40rem]">
          <CompareTable models={models} />
        </div>
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return <div className="flex min-h-[50vh] items-center justify-center px-4 text-slate-500">{children}</div>;
}
