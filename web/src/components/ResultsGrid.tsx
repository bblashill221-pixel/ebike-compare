import type { Model } from "../types";
import { BikeCard } from "./BikeCard";

export function ResultsGrid({ models }: { models: Model[] }) {
  if (!models.length) {
    return (
      <div className="card p-10 text-center text-slate-500">
        No e-bikes match these filters. Try widening the price/spec ranges or clearing a filter.
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {models.map((m) => (
        <BikeCard key={m.id} model={m} />
      ))}
    </div>
  );
}
