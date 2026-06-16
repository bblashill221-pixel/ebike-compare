#!/usr/bin/env python3
"""
Golden component-parse corpus: (brand, kind, raw label+text) -> expected parsed
dict, harvested from real scraped rows across every brand. The check re-runs
parse_components.parse_component on each case and fails on any difference, so
parser changes are provably regression-free fleet-wide.

  python golden_parse.py            # check (exit 1 on regressions)
  python golden_parse.py --update   # re-harvest the corpus from current data
                                    # (run AFTER an intended parser change,
                                    #  review the git diff of the corpus)

validate_build.py imports golden_problems() as a promotion gate.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from parse_components import parse_component
from spec_groups import snake

DATA = Path(__file__).parent / "data"
CORPUS = DATA / "golden" / "component_parse_cases.json"
PER_KIND_BRAND = 2          # cases kept per (kind, brand)
MAX_CASES = 500


def _iter_rows():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        try:
            doc = json.load(open(f))
        except ValueError:
            continue
        for m in doc.get("models", []):
            rows = (m.get("specs") or {}).get("all") or {}
            snaked = {snake(k): v for k, v in rows.items() if isinstance(v, str)}
            for label, value in rows.items():
                if isinstance(value, str):
                    yield brand, label, value, snaked


def harvest() -> list[dict]:
    cases, per_bucket, seen = [], {}, set()
    for brand, label, value, snaked in _iter_rows():
        field = snake(label)
        # brake rows borrow sibling rotor text; keep cases self-contained
        siblings = {k: v for k, v in snaked.items() if "rotor" in k}
        parsed = parse_component(field, value, brand, siblings=snaked)
        if not parsed:
            continue
        kind = parsed.get("_kind")
        key = (kind, value)
        if key in seen:
            continue
        bucket = (kind, brand)
        if per_bucket.get(bucket, 0) >= PER_KIND_BRAND:
            continue
        seen.add(key)
        per_bucket[bucket] = per_bucket.get(bucket, 0) + 1
        cases.append({"brand": brand, "field": field, "kind": kind,
                      "text": value, "siblings": siblings or None,
                      "expected": parsed})
        if len(cases) >= MAX_CASES:
            break
    return cases


def golden_problems(limit: int = 10) -> list[str]:
    """Regression descriptions (empty = corpus passes). Used by validate_build."""
    try:
        cases = json.loads(CORPUS.read_text())
    except (FileNotFoundError, ValueError):
        return []  # no corpus yet -- not a failure
    problems = []
    for c in cases:
        got = parse_component(c["field"], c["text"], c["brand"],
                              siblings=c.get("siblings") or {})
        if got != c["expected"]:
            exp, act = c["expected"], got or {}
            diff_keys = sorted(k for k in set(exp) | set(act)
                               if exp.get(k) != act.get(k))
            problems.append(
                f"golden parse changed: {c['brand']}/{c['kind']} "
                f"fields {diff_keys} for {c['text'][:60]!r}")
    if len(problems) > limit:
        problems = problems[:limit] + [
            f"... and {len(problems) - limit} more golden regressions"]
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true",
                    help="re-harvest the corpus from current scrape data")
    args = ap.parse_args()
    if args.update:
        cases = harvest()
        CORPUS.parent.mkdir(parents=True, exist_ok=True)
        CORPUS.write_text(json.dumps(cases, indent=1, ensure_ascii=False))
        kinds = sorted({c["kind"] for c in cases})
        brands = sorted({c["brand"] for c in cases})
        print(f"[*] wrote {len(cases)} cases ({len(kinds)} kinds, "
              f"{len(brands)} brands) -> {CORPUS}")
        return
    problems = golden_problems(limit=20)
    if problems:
        print(f"[golden] {len(problems)} problem(s):")
        for p in problems:
            print(f"   - {p}")
        sys.exit(1)
    n = len(json.loads(CORPUS.read_text())) if CORPUS.exists() else 0
    print(f"[golden] OK — {n} cases pass")


if __name__ == "__main__":
    main()
