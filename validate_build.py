#!/usr/bin/env python3
"""
Build sanity gate: compare the freshly-built normalized fleet to the previous
build and fail (exit 1) if it looks broken, so a bad scrape/normalize isn't
promoted ("pending no scraping or normalizing issues"). Advisory — run before
diff_changes / before publishing to the web.

Checks (thresholds below; tune freely):
  * total model count didn't drop more than MAX_COUNT_DROP
  * no brand that had models in the baseline is now at 0 (a brand scrape broke)
  * no core typed-field coverage regressed more than MAX_COVERAGE_DROP points
    (a parser broke fleet-wide)

Exit 0 = OK to promote; exit 1 = problems (printed). No network, idempotent.

Usage:  python validate_build.py [-i ebikes_normalized.json] [--baseline path]
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "current" / "active" / "ebikes_normalized.json"

MAX_COUNT_DROP = 0.20      # fail if today's count < (1 - this) * baseline count
MAX_COVERAGE_DROP = 15     # fail if a core field's % coverage drops > this many points
CORE_FIELDS = ["motor_w", "battery_wh", "weight_lb", "range_mi", "brake_type",
               "frame_material", "drive_type"]


def _by_brand(models: list) -> dict:
    out: dict = {}
    for m in models:
        out[m.get("brand")] = out.get(m.get("brand"), 0) + 1
    return out


def _coverage(models: list) -> dict:
    n = len(models) or 1
    cov = {}
    for f in CORE_FIELDS:
        c = sum(1 for m in models
                if (m.get("analysis") or {}).get("specs_typed", {}).get(f) not in (None, "", [], {}))
        cov[f] = round(100 * c / n)
    return cov


def find_baseline() -> Path | None:
    dirs = sorted(p for p in glob.glob(str(DATA / "legacy" / "*"))
                  if Path(p, "ebikes_normalized.json").exists())
    return Path(dirs[-1], "ebikes_normalized.json") if dirs else None


def validate(cur: list, base: list) -> list[str]:
    problems: list[str] = []
    if base and len(cur) < (1 - MAX_COUNT_DROP) * len(base):
        problems.append(f"model count dropped {len(base)} -> {len(cur)} "
                        f"(> {int(MAX_COUNT_DROP * 100)}%)")
    cb, bb = _by_brand(cur), _by_brand(base)
    for brand, cnt in sorted(bb.items()):
        if cnt > 0 and cb.get(brand, 0) == 0:
            problems.append(f"brand '{brand}' went {cnt} -> 0 models")
    cc, bc = _coverage(cur), _coverage(base)
    for f in CORE_FIELDS:
        if bc[f] - cc[f] > MAX_COVERAGE_DROP:
            problems.append(f"{f} coverage {bc[f]}% -> {cc[f]}% (drop > {MAX_COVERAGE_DROP} pts)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="Sanity-gate the new normalized build vs the previous one.")
    ap.add_argument("-i", "--input", default=str(ACTIVE))
    ap.add_argument("--baseline", default=None)
    args = ap.parse_args()

    cur = json.load(open(args.input)).get("models", [])
    bpath = Path(args.baseline) if args.baseline else find_baseline()
    if not bpath or not bpath.exists():
        print("[validate] no baseline to compare against — skipping (first build).")
        return 0
    base = json.load(open(bpath)).get("models", [])
    problems = validate(cur, base)
    label = bpath.parent.name
    if problems:
        print(f"[validate] FAILED vs {label}: {len(problems)} issue(s)")
        for p in problems:
            print("   -", p)
        return 1
    print(f"[validate] OK vs {label}: {len(cur)} models across {len(_by_brand(cur))} brands; "
          f"core coverage {_coverage(cur)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
