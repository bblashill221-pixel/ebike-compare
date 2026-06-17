import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { QUESTIONS, setSkipQuiz } from "../findMyEbike";

// Beginner questionnaire: each dropdown answer carries the technical filter
// params it contributes (see findMyEbike.ts). Answers are optional; "Find My
// eBike!" builds a query string and hands off to Browse, which hydrates the
// filters from it.
export function FindMyEbike() {
  const navigate = useNavigate();
  // questionId -> set of checked choice indices (none = no preference)
  const [answers, setAnswers] = useState<Record<string, number[]>>({});
  const [skipOpen, setSkipOpen] = useState(false);
  const [hideFuture, setHideFuture] = useState(false);

  const toggle = (qid: string, i: number) =>
    setAnswers((a) => {
      const cur = a[qid] ?? [];
      return { ...a, [qid]: cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i] };
    });

  const skipToBikes = () => {
    if (hideFuture) setSkipQuiz(true);
    navigate("/");
  };

  const search = useMemo(() => {
    // Gather every checked choice's params. Non-price keys reduce per key: enum
    // keys (type/sensor/frame) merge to a de-duped CSV (Browse containsAny);
    // numeric keys collapse to the most permissive bound (a *_max widens to the
    // largest ceiling, everything else to the smallest floor).
    const vals: Record<string, string[]> = {};
    // Price spans the LOWEST selected floor to the HIGHEST selected ceiling. An
    // open-ended tier ("≤ $1,200" has no floor, "$9,000+" no ceiling) drops that
    // end to the catalog bound — so it's only set when EVERY selected price tier
    // supplies that end (e.g. ≤$1,200 + $1,000–$2,000 -> floor opens -> [low, 2000]).
    let priceN = 0;
    const pMin: number[] = [];
    const pMax: number[] = [];
    for (const q of QUESTIONS) {
      for (const i of answers[q.id] ?? []) {
        const p = q.choices[i]?.params;
        if (!p) continue;
        if ("price_min" in p || "price_max" in p) {
          priceN++;
          if (p.price_min != null) pMin.push(Number(p.price_min));
          if (p.price_max != null) pMax.push(Number(p.price_max));
        }
        for (const [k, v] of Object.entries(p)) {
          if (k === "price_min" || k === "price_max") continue;
          (vals[k] ??= []).push(v);
        }
      }
    }
    const sp = new URLSearchParams();
    if (priceN) {
      if (pMin.length === priceN) sp.set("price_min", String(Math.min(...pMin)));
      if (pMax.length === priceN) sp.set("price_max", String(Math.max(...pMax)));
    }
    for (const [k, list] of Object.entries(vals)) {
      const nums = list.map(Number);
      if (nums.every((n) => !Number.isNaN(n))) {
        sp.set(k, String(k.endsWith("_max") ? Math.max(...nums) : Math.min(...nums)));
      } else {
        sp.set(k, [...new Set(list.flatMap((v) => v.split(",")))].join(","));
      }
    }
    return sp.toString();
  }, [answers]);

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
        bikes that fit. Skip anything you're unsure about.
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
            {/* stacked on mobile, inline on one line (wrapping) from `sm` up */}
            <div className="mt-1.5 flex flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:gap-x-5">
              {q.choices.map((c, i) =>
                // unchecked = no preference, so the explicit "No preference" option
                // isn't shown as a checkbox
                c.label === "No preference" ? null : (
                  <label key={i} className="flex items-center gap-2 whitespace-nowrap text-sm text-slate-700">
                    <input
                      type="checkbox"
                      checked={(answers[q.id] ?? []).includes(i)}
                      onChange={() => toggle(q.id, i)}
                      className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    {c.label}
                  </label>
                ),
              )}
            </div>
          </fieldset>
          );
        })}
      </div>

      <div className="mt-7">
        <button
          type="button"
          onClick={submit}
          className="w-full cursor-pointer rounded-lg bg-brand-600 px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-brand-700 sm:w-auto sm:px-8"
        >
          Find My eBike!
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
