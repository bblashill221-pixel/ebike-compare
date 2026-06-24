// DEV-ONLY debug overlay: breaks down every input that produces a model's `value`
// dimension score. Rendered only when import.meta.env.DEV (see ScoreBars), so it is
// tree-shaken out of production builds — never shown to real users.
import type { ReactNode } from "react";
import type { Model, SpecValue } from "../types";
import { lowestPrice } from "../pricing";

/** A rehydrated component leaf carries `_kind` + (usually) `retail_usd`. */
function isComponent(v: SpecValue): v is Record<string, SpecValue> {
  return !!v && typeof v === "object" && !Array.isArray(v) && "_kind" in v;
}

interface PartRow {
  group: string;
  field: string;
  label: string;
  kind: string;
  retail: number | null;
}

/** Walk the (rehydrated) grouped specs and pull every parsed component leaf with its retail. */
function collectParts(model: Model): PartRow[] {
  const out: PartRow[] = [];
  for (const [group, fields] of Object.entries(model.specs ?? {})) {
    if (!fields || typeof fields !== "object") continue;
    for (const [field, v] of Object.entries(fields)) {
      if (!isComponent(v)) continue;
      const man = typeof v.manufacturer === "string" ? v.manufacturer : "";
      const mdl = typeof v.model === "string" ? v.model : "";
      const label = [man, mdl].filter(Boolean).join(" ") || (typeof v.details === "string" ? v.details : field);
      const r = typeof v.retail_usd === "number" ? v.retail_usd : null;
      out.push({ group, field, label, kind: String(v._kind), retail: r });
    }
  }
  return out.sort((a, b) => (b.retail ?? -1) - (a.retail ?? -1));
}

const usd = (n: number | null | undefined) =>
  n == null ? "—" : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

export function ValueScoreDebug({ model, onClose }: { model: Model; onClose: () => void }) {
  const cq = model.analysis?.component_quality;
  const score = model.analysis?.scores?.value;
  const cohort = model.analysis?.primary_type ?? "Commuter / Urban";
  const price = lowestPrice(model);
  const parts = collectParts(model);
  const knownRetail = parts.reduce((s, p) => s + (p.retail ?? 0), 0);

  const Row = ({ k, v, note }: { k: string; v: ReactNode; note?: string }) => (
    <div className="flex items-baseline justify-between gap-4 border-b border-slate-100 py-1">
      <span className="text-slate-500">{k}</span>
      <span className="text-right">
        <span className="font-mono tabular-nums text-slate-800">{v}</span>
        {note && <span className="ml-2 text-[11px] text-slate-400">{note}</span>}
      </span>
    </div>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-amber-600">
              ⚙ dev · value score breakdown
            </div>
            <h3 className="font-semibold text-slate-800">{model.model}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          >
            ✕
          </button>
        </div>

        <div className="mb-4 text-sm">
          <Row k="value score" v={score != null ? Math.round(score) : "—"} note="(1 − cohort rank) × 100" />
          <Row k="cohort" v={cohort} note="ranked vs these peers" />
          <Row k="value_ratio" v={cq?.value_ratio ?? "—"} note="price ÷ base · lower = better" />
          <Row k="price (lowest)" v={usd(price)} />
          <Row k="component_base_value_usd" v={usd(cq?.component_base_value_usd)} note="costed parts base" />
          <Row k="bom_pct" v={cq?.bom_pct != null ? `${(cq.bom_pct * 100).toFixed(1)}%` : "—"} note="base ÷ price" />
          <Row k="component_retail_value_usd" v={usd(cq?.component_retail_value_usd)} note="identified parts retail" />
          <Row k="parts identified / priced" v={`${cq?.parts_identified ?? "—"} / ${cq?.parts_priced ?? "—"}`} />
          <Row k="parts costed / researched" v={`${cq?.parts_costed ?? "—"} / ${cq?.parts_researched ?? "—"}`} />
        </div>

        {(() => {
          // Show EVERY cost that sums to component_base_value_usd — parsed parts AND the
          // typed-spec system estimates (battery/motor/frame) — so nothing is invisible.
          const bb = cq?.base_breakdown ?? [];
          const sum = bb.reduce((s, p) => s + (p.cost ?? 0), 0);
          const tag = (m: string) =>
            m === "researched" ? "researched" : m === "spec_estimate" ? "est. from specs" : "est.";
          return bb.length ? (
            <>
              <div className="mb-1 text-xs font-semibold text-slate-600">
                Base breakdown ({bb.length} costs · sum {usd(sum)})
              </div>
              <table className="w-full text-xs">
                <tbody>
                  {bb.map((p, i) => (
                    <tr key={i} className="border-b border-slate-50">
                      <td className="py-0.5 pr-2 text-slate-400">{p.kind}</td>
                      <td className="py-0.5 pr-2 text-slate-700">
                        {p.label}
                        <span className="ml-1 text-[10px] text-slate-400">({tag(p.method)})</span>
                      </td>
                      <td className="py-0.5 text-right font-mono tabular-nums text-slate-800">{usd(p.cost)}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-slate-200 font-semibold">
                    <td className="py-0.5 pr-2 text-slate-500" colSpan={2}>component_base_value_usd</td>
                    <td className="py-0.5 text-right font-mono tabular-nums text-slate-900">{usd(sum)}</td>
                  </tr>
                </tbody>
              </table>
            </>
          ) : (
            <div className="mb-1 text-xs font-semibold text-slate-600">
              Per-part retail ({parts.length} components · known sum {usd(knownRetail)})
            </div>
          );
        })()}
        <p className="mt-3 text-[11px] leading-snug text-slate-400">
          Every line above is summed into <span className="font-mono">component_base_value_usd</span>.
          "est. from specs" rows cost a core system (battery / motor / frame) from the typed specs
          when no branded part was parsed. The value score is the inverted rank of{" "}
          <span className="font-mono">value_ratio</span> within the {cohort} cohort.
        </p>
      </div>
    </div>
  );
}
