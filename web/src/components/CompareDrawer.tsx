import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare, MAX_COMPARE } from "../compare/CompareContext";
import { primaryImage } from "./BikeCard";
import type { Model } from "../types";

// Cart-style compare "bucket": a floating count button opens a panel that slides in
// from the right (from the top on mobile). Auto-opens when a bike is added.
export function CompareDrawer() {
  const { byId, status } = useData();
  const { ids, remove, reorder, clear } = useCompare();
  const [open, setOpen] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);   // bike being dragged
  const [overId, setOverId] = useState<string | null>(null);   // bike currently hovered as drop target
  const navigate = useNavigate();

  // Only bikes that still exist in the current catalog. A bike can leave the dataset
  // between visits (discontinued / dropped in a scrape) while its id lingers in the
  // saved tray, so everything below counts/renders from `models`, not raw `ids`.
  const models = ids.map((id) => byId.get(id)).filter((m): m is Model => !!m);
  const count = models.length;
  const canCompare = count >= 2;

  const prevLen = useRef(count);
  // auto-open when a bike is added (cart behavior)
  useEffect(() => {
    if (count > prevLen.current) setOpen(true);
    if (count === 0) setOpen(false);
    prevLen.current = count;
  }, [count]);

  // Prune tray entries whose bike has left the catalog, so the saved tray and every
  // count stay in sync with what's actually available. Runs once data is loaded.
  useEffect(() => {
    if (status !== "ready") return;
    ids.forEach((id) => {
      if (!byId.has(id)) remove(id);
    });
  }, [status, byId, ids, remove]);

  const goCompare = () => {
    setOpen(false);
    navigate(`/compare?ids=${encodeURIComponent(models.map((m) => m.id).join(","))}`);
  };

  return (
    <>
      {/* floating toggle (only when the bucket has bikes) */}
      {count > 0 && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="fixed right-4 top-20 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-brand-600 text-white shadow-lg transition-colors hover:bg-brand-700"
          aria-label={`Open compare list (${count} bikes)`}
        >
          <span className="text-lg">⚖</span>
          <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-rose-500 text-xs font-bold">
            {count}
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
              Compare <span className="text-sm font-normal text-slate-400">({count}/{MAX_COMPARE})</span>
            </h2>
            <button type="button" onClick={() => setOpen(false)} className="text-slate-400 hover:text-slate-700" aria-label="Close">
              ✕
            </button>
          </div>
          {canCompare && (
            <button type="button" onClick={goCompare} className="btn-primary mt-3 w-full">
              Compare {ids.length} eBikes →
            </button>
          )}
          {!canCompare && ids.length > 0 && (
            <p className="mt-3 text-xs text-slate-400">Add at least one more eBike to compare.</p>
          )}
        </div>

        <ul className="space-y-3 p-4">
          {models.map(
            (m) =>
              m && (
                <li
                  key={m.id}
                  onDragOver={(e) => {
                    if (!dragId || dragId === m.id) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    if (overId !== m.id) setOverId(m.id);
                  }}
                  onDragLeave={() => setOverId((cur) => (cur === m.id ? null : cur))}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (dragId && dragId !== m.id) reorder(dragId, m.id);
                    setDragId(null);
                    setOverId(null);
                  }}
                  className={`flex items-start gap-2 rounded-xl border p-3 transition-colors ${
                    dragId === m.id ? "opacity-40" : ""
                  } ${
                    overId === m.id && dragId && dragId !== m.id
                      ? "border-brand-400 ring-2 ring-brand-200"
                      : "border-slate-200"
                  }`}
                >
                  {/* drag handle: only the grip starts a drag, so the link stays clickable */}
                  <span
                    draggable
                    onDragStart={(e) => {
                      setDragId(m.id);
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", m.id);
                    }}
                    onDragEnd={() => {
                      setDragId(null);
                      setOverId(null);
                    }}
                    className="mt-1 flex shrink-0 cursor-grab touch-none items-center text-slate-300 hover:text-slate-500 active:cursor-grabbing"
                    aria-label="Drag to reorder"
                    title="Drag to reorder"
                  >
                    <svg width="10" height="16" viewBox="0 0 10 16" fill="currentColor" aria-hidden>
                      <circle cx="2.5" cy="3" r="1.3" /><circle cx="7.5" cy="3" r="1.3" />
                      <circle cx="2.5" cy="8" r="1.3" /><circle cx="7.5" cy="8" r="1.3" />
                      <circle cx="2.5" cy="13" r="1.3" /><circle cx="7.5" cy="13" r="1.3" />
                    </svg>
                  </span>
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/bike/${encodeURIComponent(m.id)}`}
                      onClick={() => setOpen(false)}
                      draggable={false}
                      className="group flex items-center gap-3"
                    >
                      <div className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-slate-50">
                        {primaryImage(m) ? (
                          <img src={primaryImage(m)!} alt={m.model} draggable={false} className="h-full w-full object-contain" />
                        ) : (
                          <div className="flex h-full items-center justify-center text-xs text-slate-300">no image</div>
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs font-medium uppercase tracking-wide text-brand-600">{m.brand}</div>
                        <div className="line-clamp-2 text-sm font-semibold text-slate-900 group-hover:text-brand-700">
                          {m.model}
                        </div>
                      </div>
                    </Link>
                    <button
                      type="button"
                      onClick={() => remove(m.id)}
                      className="mt-2 text-xs font-medium text-rose-600 hover:underline"
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ),
          )}
        </ul>

        {count > 0 && (
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
