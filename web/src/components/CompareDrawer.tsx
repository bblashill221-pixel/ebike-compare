import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare, MAX_COMPARE } from "../compare/CompareContext";
import { primaryImage } from "./BikeCard";

// Cart-style compare "bucket": a floating count button opens a panel that slides in
// from the right (from the top on mobile). Auto-opens when a bike is added.
export function CompareDrawer() {
  const { byId } = useData();
  const { ids, remove, clear } = useCompare();
  const [open, setOpen] = useState(false);
  const prevLen = useRef(ids.length);
  const navigate = useNavigate();

  // auto-open when a bike is added (cart behavior)
  useEffect(() => {
    if (ids.length > prevLen.current) setOpen(true);
    if (ids.length === 0) setOpen(false);
    prevLen.current = ids.length;
  }, [ids.length]);

  const models = ids.map((id) => byId.get(id)).filter(Boolean);
  const canCompare = ids.length >= 2;

  const goCompare = () => {
    setOpen(false);
    navigate(`/compare?ids=${encodeURIComponent(ids.join(","))}`);
  };

  return (
    <>
      {/* floating toggle (only when the bucket has bikes) */}
      {ids.length > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="fixed right-4 top-20 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-brand-600 text-white shadow-lg transition-colors hover:bg-brand-700"
          aria-label={`Open compare list (${ids.length} bikes)`}
        >
          <span className="text-lg">⚖</span>
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-rose-500 text-xs font-bold">
            {ids.length}
          </span>
        </button>
      )}

      {/* backdrop: mobile only — on desktop the drawer floats so you can keep
          browsing and adding bikes while it is open */}
      {open && (
        <div className="fixed inset-0 z-40 bg-black/30 sm:hidden" onClick={() => setOpen(false)} />
      )}

      {/* panel: slides from the top on mobile, from the right on sm+ */}
      <div
        className={`fixed z-50 bg-white shadow-2xl transition-transform duration-300
          inset-x-0 top-0 max-h-[75vh] overflow-auto rounded-b-2xl
          sm:inset-x-auto sm:inset-y-0 sm:right-0 sm:w-80 sm:max-h-none sm:rounded-none
          ${open ? "translate-x-0 translate-y-0" : "-translate-y-full sm:translate-y-0 sm:translate-x-full"}`}
        role="dialog"
        aria-label="Compare list"
      >
        <div className="sticky top-0 border-b border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-slate-800">
              Compare <span className="text-sm font-normal text-slate-400">({ids.length}/{MAX_COMPARE})</span>
            </h2>
            <button type="button" onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700" aria-label="Close">
              ✕
            </button>
          </div>
          {canCompare && (
            <button type="button" onClick={goCompare} className="btn-primary mt-3 w-full">
              Compare {ids.length} e-bikes →
            </button>
          )}
          {!canCompare && ids.length > 0 && (
            <p className="mt-3 text-xs text-slate-400">Add at least one more e-bike to compare.</p>
          )}
        </div>

        <ul className="space-y-3 p-4">
          {models.map(
            (m) =>
              m && (
                <li key={m.id} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex items-center gap-3">
                    <div className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-slate-50">
                      {primaryImage(m) ? (
                        <img src={primaryImage(m)!} alt={m.model} className="h-full w-full object-contain" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-slate-300">no image</div>
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{m.brand}</div>
                      <Link
                        to={`/bike/${encodeURIComponent(m.id)}`}
                        onClick={() => setOpen(false)}
                        className="line-clamp-2 text-sm font-semibold text-slate-900 hover:text-brand-700"
                      >
                        {m.model}
                      </Link>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(m.id)}
                    className="mt-2 text-xs font-medium text-rose-600 hover:underline"
                  >
                    Remove
                  </button>
                </li>
              ),
          )}
        </ul>

        {ids.length > 0 && (
          <div className="px-4 pb-4">
            <button type="button" onClick={clear} className="text-xs text-slate-400 hover:text-slate-600 hover:underline">
              Clear all
            </button>
          </div>
        )}
      </div>
    </>
  );
}
