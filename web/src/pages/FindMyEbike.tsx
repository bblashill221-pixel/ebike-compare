import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { QUESTIONS, setSkipQuiz } from "../findMyEbike";

// Beginner questionnaire: each dropdown answer carries the technical filter
// params it contributes (see findMyEbike.ts). Answers are optional; "Find My
// eBike!" builds a query string and hands off to Browse, which hydrates the
// filters from it.
export function FindMyEbike() {
  const navigate = useNavigate();
  // questionId -> selected choice index (defaults to the first choice)
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [skipOpen, setSkipOpen] = useState(false);
  const [hideFuture, setHideFuture] = useState(false);

  const skipToBikes = () => {
    if (hideFuture) setSkipQuiz(true);
    navigate("/");
  };

  const search = useMemo(() => {
    const sp = new URLSearchParams();
    for (const q of QUESTIONS) {
      const choice = q.choices[answers[q.id] ?? 0];
      for (const [k, v] of Object.entries(choice.params)) {
        const prev = sp.get(k);
        // two questions can target the same key (e.g. product type) -> merge CSV
        sp.set(k, prev ? `${prev},${v}` : v);
      }
    }
    return sp.toString();
  }, [answers]);

  const submit = () =>
    navigate({ pathname: "/", search: search ? `?${search}` : "" });

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-800">Find My eBike</h1>
      <p className="mt-1 text-sm text-slate-500">
        Answer as many or as few questions as you like — we'll narrow the catalog to
        bikes that fit. Skip anything you're unsure about.
      </p>

      <div className="mt-6 space-y-5">
        {QUESTIONS.map((q) => (
          <div key={q.id}>
            <label
              htmlFor={`fme-${q.id}`}
              className="block text-sm font-semibold text-slate-700"
            >
              {q.label}
            </label>
            {q.help && <p className="text-xs text-slate-400">{q.help}</p>}
            <select
              id={`fme-${q.id}`}
              value={answers[q.id] ?? 0}
              onChange={(e) =>
                setAnswers({ ...answers, [q.id]: Number(e.target.value) })
              }
              className="mt-1 w-full rounded border-slate-300 text-sm focus:border-brand-500 focus:ring-brand-500"
            >
              {q.choices.map((c, i) => (
                <option key={i} value={i}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        ))}
      </div>

      <div className="mt-7 flex items-center gap-4">
        <button
          type="button"
          onClick={submit}
          className="flex-1 cursor-pointer rounded-lg bg-brand-600 px-4 py-2.5 text-center text-sm font-semibold text-white hover:bg-brand-700"
        >
          Find My eBike!
        </button>
        <button
          type="button"
          onClick={() => setSkipOpen(true)}
          className="cursor-pointer text-sm text-slate-500 hover:text-slate-700 hover:underline"
        >
          Skip
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
