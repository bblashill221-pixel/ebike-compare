import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { QUESTIONS, answersFromFilters, filtersFromParams, searchFromAnswers, setSkipQuiz } from "../findMyEbike";
import { loadStoredFilters, saveStoredFilters } from "../filterStorage";
import { useData } from "../data/DataProvider";
import { runSearch } from "../search/orama";
import { useShowSoldOut } from "../soldOut";
import { useUnits } from "../units";

// Beginner questionnaire: each dropdown answer carries the technical filter
// params it contributes (see findMyEbike.ts). Answers are optional; "Find My
// eBike!" builds a query string and hands off to Browse, which hydrates the
// filters from it.
export function FindMyEbike() {
  const navigate = useNavigate();
  const { db, models, rangeBounds, status } = useData();
  const [showSoldOut] = useShowSoldOut();
  const [units] = useUnits();
  // questionId -> set of checked choice indices (none = no preference). Seed from the
  // active Browse filters so navigating back from the listing pre-selects the matching
  // answers (inverse of the answers -> params -> filters hand-off).
  const [answers, setAnswers] = useState<Record<string, number[]>>(
    () => answersFromFilters(loadStoredFilters()),
  );
  const [skipOpen, setSkipOpen] = useState(false);
  const [hideFuture, setHideFuture] = useState(false);
  // live count of bikes matching the answers so far (null until the index is ready)
  const [count, setCount] = useState<number | null>(null);

  // Persist the answer-derived filters to the shared Browse filter store on every
  // change, so editing an answer immediately updates the filter settings (matching the
  // full-replace Browse does on the final hand-off). Skipped until the index is ready
  // so the range bands resolve against real bounds.
  const persist = (next: Record<string, number[]>) => {
    if (status !== "ready") return;
    saveStoredFilters(
      filtersFromParams(new URLSearchParams(searchFromAnswers(next)), rangeBounds),
    );
  };

  // Single-select per question: picking a choice replaces the answer. Questions
  // start with NOTHING selected; `clear` removes the answer (back to blank) and is
  // offered via a trailing "No preference" radio only once a choice has been made.
  const select = (qid: string, i: number) => {
    const next = { ...answers, [qid]: [i] };
    setAnswers(next);
    persist(next);
  };
  const clear = (qid: string) => {
    const next = { ...answers };
    delete next[qid];
    setAnswers(next);
    persist(next);
  };

  const skipToBikes = () => {
    if (hideFuture) setSkipQuiz(true);
    navigate("/");
  };

  const search = useMemo(() => searchFromAnswers(answers), [answers]);

  // Real-time match count: run the SAME filter pipeline Browse uses on the params
  // the answers produce, so the number on the button is exactly what the results
  // page will show. Term is "" (the quiz has no search box).
  useEffect(() => {
    if (status !== "ready" || !db) return;
    let cancelled = false;
    const filters = filtersFromParams(new URLSearchParams(search), rangeBounds);
    runSearch(db, "", filters, models.length, showSoldOut, units).then((res) => {
      if (!cancelled) setCount(res.count);
    });
    return () => {
      cancelled = true;
    };
  }, [search, db, status, units, showSoldOut, rangeBounds, models.length]);

  const submit = () =>
    navigate({ pathname: "/", search: search ? `?${search}` : "" });

  return (
    <div className="max-w-5xl py-8 pr-4 pl-6 sm:pl-12 lg:pl-24">
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-bold text-slate-800">Find My eBike</h1>
        <button
          type="button"
          onClick={() => setSkipOpen(true)}
          className="cursor-pointer text-sm text-slate-500 hover:text-slate-700 hover:underline"
        >
          Skip
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Answer as many or as few questions as you like — we'll narrow the catalog to
        eBikes that fit. Skip anything you're unsure about.
      </p>

      <div className="mt-6 space-y-4">
        {QUESTIONS.map((q, i) => {
          // render a trailing "(...)" note (e.g. "(determining type)") in a lighter font
          const paren = q.label.match(/\s*(\([^)]*\))\s*$/);
          const main = paren ? q.label.slice(0, paren.index) : q.label;
          return (
          <fieldset key={q.id}>
            <legend className="block text-sm font-semibold text-slate-700">
              <span className="text-slate-400">{i + 1}.</span> {main}
              {paren && <span className="ml-1 font-normal text-slate-400">{paren[1]}</span>}
              {q.help && <span className="ml-2 text-xs font-normal text-slate-400">{q.help}</span>}
            </legend>
            {/* stacked on mobile, inline on one line (wrapping) from `sm` up.
                Single-select radios; nothing is selected by default. Once a choice
                is made, a trailing "No preference" radio appears to clear it. */}
            <div className="mt-1.5 flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:gap-x-5">
              {q.choices.map((c, i) =>
                c.label === "No preference" ? null : (
                  <label key={i} className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-700">
                    <input
                      type="radio"
                      name={q.id}
                      checked={answers[q.id]?.[0] === i}
                      onChange={() => select(q.id, i)}
                      className="border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    {c.label}
                  </label>
                ),
              )}
              {answers[q.id]?.length ? (
                <label className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-400">
                  <input
                    type="radio"
                    name={q.id}
                    checked={false}
                    onChange={() => clear(q.id)}
                    className="border-slate-300 text-brand-600 focus:ring-brand-500"
                  />
                  No preference
                </label>
              ) : null}
            </div>
          </fieldset>
          );
        })}
      </div>

      {/* Sticky action bar: stays visible while scrolling the questions so the live
          match count (shown on the button) and the empty-set notice are always in view. */}
      <div className="sticky bottom-0 mt-7 border-t border-slate-200 bg-white/95 py-3 backdrop-blur">
        {count === 0 && (
          <p className="mb-2 text-sm font-medium text-amber-700">
            No eBikes match your criteria yet — try clearing some answers or raising your budget.
          </p>
        )}
        <button
          type="button"
          onClick={submit}
          className="w-full cursor-pointer rounded-lg bg-brand-600 px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-brand-700 sm:w-auto sm:px-8"
        >
          Find My eBike!
          {count != null && (
            <span className="ml-1.5 font-normal text-brand-100">
              · {count} {count === 1 ? "eBike" : "eBikes"}
            </span>
          )}
        </button>
      </div>

      {skipOpen && (
        <div
          className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 px-4"
          role="dialog"
          aria-modal="true"
          aria-label="Skip the questions"
          onClick={() => setSkipOpen(false)}
        >
          <div
            className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <p className="text-sm text-slate-600">
              No problem — you can browse the full catalog and filter it yourself.
            </p>
            <label className="mt-4 flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={hideFuture}
                onChange={(e) => setHideFuture(e.target.checked)}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              Hide this screen in the future
            </label>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setSkipOpen(false)}
                className="cursor-pointer rounded-lg px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={skipToBikes}
                className="cursor-pointer rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-700"
              >
                Go to the eBikes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
