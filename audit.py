#!/usr/bin/env python3
"""
Data audit: flag models missing expected spec values.

Runs as the LAST pipeline stage (after analyze.py) over the normalized typed specs
(`analysis.specs_typed`). For every model it checks the EXPECTED_FIELDS below and
records a row (brand, model, field) wherever the typed value is null/empty, so spec
gaps -- e.g. a motor that never got a parsed wattage, or the Himiway-C5 torque that
lived in an unscraped page block -- surface for review instead of shipping silently.

EXPECTED_FIELDS is a curated, deliberately-editable list: tune it as the notion of
"expected for every model" sharpens. Conditional fields (gears on single-speeds,
peak watts, water resistance, ...) are intentionally NOT here.

Outputs (all of):
  - console: a coverage table for every typed field + a missing-by-field summary;
  - data/current/data_audit.json: coverage + the full brand/model/field missing list;
  - data/current/data_audit_missing.csv: the missing rows for spreadsheet triage;
  - a `data_audit` block stamped onto each model in ebikes_normalized.json.

Usage:  python audit.py [-i data/current/active/ebikes_normalized.json]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# (typed_specs key, human label). Only these generate "missing" flag rows; every
# other typed field still appears in the coverage table. Review/tune freely.
EXPECTED_FIELDS: list[tuple[str, str]] = [
    # core -- essentially universal for any e-bike
    ("motor_w", "Motor power (W)"),
    ("battery_wh", "Battery capacity (Wh)"),
    ("weight_lb", "Weight (lb)"),
    ("range_mi", "Range (mi)"),
    ("brake_type", "Brake type"),
    ("frame_material", "Frame material"),
    ("drive_type", "Motor placement"),
    # expected for most (under review)
    ("torque_nm", "Motor torque (Nm)"),
    ("warranty_years", "Warranty (years)"),
    ("display_type", "Display type"),
    ("drivetrain_type", "Drivetrain type"),
    ("suspension", "Suspension"),
    ("cell_brand", "Battery cell brand"),
]


def _has_rear_rack(model: dict) -> bool:
    """The bike ships with / is built around a rear rack (so a rack load capacity
    should be published): a rack in the included accessories, or a cargo bike."""
    accs = " ".join(a.get("name", "") for a in (model.get("included_accessories") or []))
    if re.search(r"rack", accs, re.I):
        return True
    return any("Cargo" in p for p in (model.get("product_types") or []))


# Expected only when the predicate holds for a model: (key, label, predicate).
# Bike payload (max_load_lb) is deliberately NOT required (often unlisted); a rear
# rack's capacity is, but only for bikes that actually have a rear rack.
CONDITIONAL_FIELDS = [
    ("rack_load_lb", "Rear-rack load (lb)", _has_rear_rack),
]


def _present(v) -> bool:
    """A typed value counts as present unless it's null or an empty string/list/dict."""
    return v not in (None, "", [], {})


def _typed(model: dict) -> dict:
    return (model.get("analysis") or {}).get("specs_typed") or {}


def audit(models: list[dict]) -> dict:
    n = len(models)
    expected_keys = [k for k, _ in EXPECTED_FIELDS]
    labels = {**dict(EXPECTED_FIELDS), **{k: lbl for k, lbl, _ in CONDITIONAL_FIELDS}}

    # coverage over EVERY typed key seen anywhere (the full field list)
    cov: dict[str, int] = {}
    for m in models:
        for k, v in _typed(m).items():
            cov.setdefault(k, 0)
            if _present(v):
                cov[k] += 1
    # make sure expected keys appear even if absent everywhere
    for k in expected_keys:
        cov.setdefault(k, 0)
    coverage = {
        k: {"count": cov[k], "pct": round(100 * cov[k] / n) if n else 0}
        for k in sorted(cov, key=lambda k: (-cov[k], k))
    }

    # per-(brand, model, field) missing rows, and per-model missing-field lists
    missing: list[dict] = []
    for m in models:
        t = _typed(m)
        gaps = [k for k in expected_keys if not _present(t.get(k))]
        gaps += [k for k, _, pred in CONDITIONAL_FIELDS
                 if pred(m) and not _present(t.get(k))]
        m["data_audit"] = {"missing": gaps}      # annotate every model (empty when clean)
        brand, name = m.get("brand", ""), m.get("model", "")
        for k in gaps:
            missing.append({"brand": brand, "model": name, "field": k, "label": labels[k]})
    missing.sort(key=lambda r: (r["brand"], r["model"], r["field"]))

    flag_keys = expected_keys + [k for k, _, _ in CONDITIONAL_FIELDS]
    by_field = {k: sum(1 for r in missing if r["field"] == k) for k in flag_keys}
    flagged_models = sum(1 for m in models if m["data_audit"]["missing"])

    # Frame-style review queue: models the pipeline couldn't resolve from page
    # text OR the curated image-inferred override. These are the ONLY ones an
    # update needs a human/vision glance for -- existing verdicts are cached in
    # data/frame_style_overrides.json (a dict lookup), never re-derived here. So
    # on a routine update this list is just the new/unresolved bikes.
    frame_review = [{"brand": m.get("brand", ""), "model": m.get("model", ""), "id": m.get("id", "")}
                    for m in models if not m.get("frame_style")]
    frame_review.sort(key=lambda r: (r["brand"], r["model"]))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_models": n,
        "expected_fields": flag_keys,
        "coverage": coverage,
        "missing": missing,
        "frame_style_review": frame_review,
        "summary": {
            "models_flagged": flagged_models,
            "missing_rows": len(missing),
            "missing_by_field": by_field,
            "frame_style_review": len(frame_review),
        },
    }


def print_report(report: dict) -> None:
    n = report["total_models"]
    expected = set(report["expected_fields"])
    print(f"\nData audit — {n} models\n")
    print("  FIELD COVERAGE (typed specs)")
    print(f"    {'field':24} {'count':>5}  {'pct':>4}   expected")
    for field, c in report["coverage"].items():
        mark = "  *" if field in expected else ""
        print(f"    {field:24} {c['count']:>5}  {c['pct']:>3}%{mark}")
    s = report["summary"]
    print(f"\n  EXPECTED-FIELD GAPS  (* above)  —  {s['missing_rows']} rows across "
          f"{s['models_flagged']}/{n} models")
    for field, cnt in sorted(s["missing_by_field"].items(), key=lambda kv: -kv[1]):
        if cnt:
            print(f"    {field:24} missing on {cnt} models")
    fr = s.get("frame_style_review", 0)
    print(f"\n  FRAME-STYLE REVIEW QUEUE  —  {fr} models need a glance "
          f"(no site text + no cached override)")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit normalized models for missing expected specs.")
    ap.add_argument("-i", "--input", default=str(DATA / "current" / "active" / "ebikes_normalized.json"))
    ap.add_argument("--json", default=str(DATA / "current" / "data_audit.json"))
    ap.add_argument("--csv", default=str(DATA / "current" / "data_audit_missing.csv"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    models = doc.get("models", [])
    report = audit(models)

    # 1) console
    print_report(report)
    # 2) JSON report
    Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    # 3) CSV of the brand/model/field missing rows
    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["brand", "model", "field"])
        for r in report["missing"]:
            w.writerow([r["brand"], r["model"], r["field"]])
    # 4) frame-style review queue (the bounded "needs a glance" delta per update)
    with open(DATA / "current" / "frame_style_review.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["brand", "model", "id"])
        for r in report["frame_style_review"]:
            w.writerow([r["brand"], r["model"], r["id"]])
    # 5) per-model annotation written back into the normalized file
    Path(args.input).write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    print(f"[*] Wrote {args.json}, {args.csv}; annotated {len(models)} models in {args.input}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
