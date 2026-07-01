import { useEffect, useRef, useState } from "react";
import type { Model } from "../types";
import { BikeCard } from "./BikeCard";

const PAGE = 48; // cards rendered up front; more load as the sentinel scrolls in

export function ResultsGrid({
  models,
  selectedTypes = [],
}: {
  models: Model[];
  /** product types currently selected in the filter; the card shows the matching
   *  type pill instead of the default (primary) type when one applies. */
  selectedTypes?: string[];
}) {
  const [visible, setVisible] = useState(PAGE);
  const sentinel = useRef<HTMLDivElement | null>(null);

  // a new result set (filter/sort change) resets the window to the first page
  useEffect(() => {
    setVisible(PAGE);
  }, [models]);

  // grow the window when the sentinel near the end of the list scrolls into view
  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setVisible((v) => (v < models.length ? v + PAGE : v));
        }
      },
      { rootMargin: "800px" }, // prefetch before it's actually on screen
    );
    io.observe(node);
    return () => io.disconnect();
  }, [models.length, visible]);

  if (!models.length) {
    return (
      <div className="card p-10 text-center text-slate-500">
        No eBikes match these filters. Try widening the price/spec ranges or clearing a filter.
      </div>
    );
  }
  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {models.slice(0, visible).map((m) => (
          <BikeCard key={m.id} model={m} selectedTypes={selectedTypes} />
        ))}
      </div>
      {visible < models.length && <div ref={sentinel} className="h-1" aria-hidden />}
    </>
  );
}
