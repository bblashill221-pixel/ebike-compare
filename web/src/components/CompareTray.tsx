import { Link } from "react-router-dom";
import { useData } from "../data/DataProvider";
import { useCompare, MAX_COMPARE } from "../compare/CompareContext";
import { primaryImage } from "./BikeCard";

export function CompareTray() {
  const { byId } = useData();
  const { ids, remove, clear } = useCompare();
  if (ids.length === 0) return null;
  const models = ids.map((id) => byId.get(id)).filter(Boolean);

  return (
    <div className="sticky bottom-0 z-30 border-t border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3">
        <div className="flex flex-1 items-center gap-3 overflow-x-auto">
          <span className="shrink-0 text-sm font-semibold text-slate-600">
            Compare ({ids.length}/{MAX_COMPARE})
          </span>
          {models.map(
            (m) =>
              m && (
                <div key={m.id} className="flex shrink-0 items-center gap-2 rounded-lg border border-slate-200 px-2 py-1">
                  {primaryImage(m) ? (
                    <img src={primaryImage(m)!} alt="" className="h-8 w-8 rounded object-contain" />
                  ) : null}
                  <span className="max-w-[10rem] truncate text-xs text-slate-700">{m.model}</span>
                  <button
                    type="button"
                    onClick={() => remove(m.id)}
                    className="text-slate-400 hover:text-rose-600"
                    aria-label={`Remove ${m.model}`}
                  >
                    ✕
                  </button>
                </div>
              ),
          )}
        </div>
        <button type="button" onClick={clear} className="btn-ghost shrink-0">
          Clear
        </button>
        <Link
          to={`/compare?ids=${encodeURIComponent(ids.join(","))}`}
          className={`btn-primary shrink-0 ${ids.length < 2 ? "pointer-events-none opacity-50" : ""}`}
        >
          Compare →
        </Link>
      </div>
    </div>
  );
}
