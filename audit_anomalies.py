#!/usr/bin/env python3
"""
Correctness audit: flag bikes that look MISCLASSIFIED or MISPARSED — not just
missing a field (that's audit.py), but carrying a value that's probably wrong.

Each check encodes a domain rule (most learned from a real bug), so a rule
written once guards the whole fleet — and every future scrape — automatically,
turning "inspect every bike" into "review a short ranked triage list".

Reads data/current/active/ebikes_normalized.json; writes
data/current/anomalies.json ({generated_at, model_count, by_rule, severity
counts, anomalies:[{id,brand,model,url,rule,severity,detail}]}). Advisory only
(never fails the build); the dev-only QA page renders the report.

Usage: python audit_anomalies.py [-i active.json] [-o anomalies.json]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"

_TRIKE = re.compile(r"(?<!s)trike|tricycle", re.I)
_CARGO = re.compile(r"cargo|hauler|utility|long[\s-]?tail|xpedition", re.I)
_HYBRID = re.compile(r"hybrid|fitness", re.I)
# canonical component materials; aluminum may carry an alloy grade ("aluminum 6061")
_MATERIALS = {
    "carbon", "steel", "stainless", "stainless steel", "carbon steel", "chromoly",
    "magnesium", "titanium", "composite", "leather", "pu leather",
    "imitation leather", "rubber", "foam", "nylon", "silicone", "silica gel",
}
_ALUMINUM_OK = re.compile(r"^aluminum( [a-z0-9.-]+)?$")
# Loose bounds for typed numeric facts — wide enough that legit eMoto wattage,
# dual-battery Wh and big range CLAIMS pass; only an egregiously out-of-range
# value (almost always a parse error) trips a flag.
_BOUNDS = {
    "battery_wh": (80, 5000), "motor_w": (150, 8000), "motor_peak_w": (150, 12000),
    "torque_nm": (10, 500), "weight_lb": (14, 175), "range_mi": (5, 250),
    "gears": (1, 14), "max_speed_mph": (10, 60),
}
_SEV_RANK = {"high": 0, "medium": 1, "low": 2}


def _typed(m: dict) -> dict:
    return (m.get("analysis") or {}).get("specs_typed") or {}


def _materials(m: dict):
    """Yield every component material string in the bike's specs."""
    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("material"), str):
                yield o["material"]
            for v in o.values():
                yield from walk(v)
        elif isinstance(o, list):
            for v in o:
                yield from walk(v)
    yield from walk(m.get("specs") or {})


def audit(models: list[dict]) -> list[dict]:
    out: list[dict] = []

    def flag(m, rule, severity, detail):
        out.append({"id": m.get("id"), "brand": m.get("brand"), "model": m.get("model"),
                    "url": m.get("url"), "rule": rule, "severity": severity, "detail": detail})

    # fleet-wide enum value counts (for singleton outliers)
    enum_counts = {f: Counter() for f in
                   ("frame_material", "drive_type", "brake_type", "suspension", "sensor_type")}
    for m in models:
        t = _typed(m)
        for f, c in enum_counts.items():
            v = t.get(f)
            if v:
                c[v] += 1

    for m in models:
        name = m.get("model") or ""
        t = _typed(m)
        pts = m.get("product_types") or []

        # --- classification invariants ---
        if _TRIKE.search(name) and "Trike" not in pts:
            flag(m, "trike_not_typed", "high", f"name says trike but product_types={pts}")
        if "Trike" in pts and not _TRIKE.search(name):
            flag(m, "trike_typed_no_name", "medium", "tagged Trike but no trike/tricycle in name")
        # NB no "Cargo without signal" check here: the cargo signal often lives in
        # scrape-time tags (normalize enforces it WITH tags); tags are dropped from
        # the normalized build, so re-checking here only false-positives on legit
        # tag-derived cargo bikes (Aventon Abound, Tern GSD).
        if "Hybrid / Fitness" in pts:
            w = t.get("weight_lb")
            if isinstance(w, (int, float)) and w > 46 and not _HYBRID.search(name):
                flag(m, "hybrid_heavy", "high",
                     f"Hybrid/Fitness but {w} lb and not named hybrid/fitness")

        # --- frame sizes: size options must produce per-size entries ---
        opt_sizes = ((m.get("variant_options") or {}).get("frame_size")) or []
        if len(opt_sizes) >= 2 and (m.get("frame_size_count") or 0) < 2:
            flag(m, "frame_sizes_missing", "high",
                 f"{len(opt_sizes)} size options {opt_sizes} but frame_size_count="
                 f"{m.get('frame_size_count')}")

        # --- material canonicalization ---
        for mat in set(_materials(m)):
            low = mat.lower()
            if low not in _MATERIALS and not _ALUMINUM_OK.match(low):
                flag(m, "material_uncanonical", "medium", f"unexpected material value {mat!r}")

        # --- numeric plausibility ---
        for f, (lo, hi) in _BOUNDS.items():
            v = t.get(f)
            if isinstance(v, (int, float)) and not (lo <= v <= hi):
                flag(m, "numeric_implausible", "high", f"{f}={v} outside [{lo}, {hi}]")

        # --- value ratio sanity ---
        vr = (m.get("analysis") or {}).get("component_quality", {}).get("value_ratio")
        if isinstance(vr, (int, float)) and (vr < 1.0 or vr > 15):
            flag(m, "value_ratio_outlier", "low", f"price / parts-cost ratio = {vr}")

        # --- enum singletons (a value held by exactly one bike = misparse candidate) ---
        for f, c in enum_counts.items():
            v = t.get(f)
            if v and c[v] == 1:
                flag(m, "enum_singleton", "low", f"{f}={v!r} appears on only this bike")

    out.sort(key=lambda a: (_SEV_RANK.get(a["severity"], 9), a["rule"], a["id"] or ""))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Flag likely-misclassified / misparsed bikes.")
    ap.add_argument("-i", "--input", default=str(DATA / "current" / "active" / "ebikes_normalized.json"))
    ap.add_argument("-o", "--output", default=str(DATA / "current" / "anomalies.json"))
    args = ap.parse_args()

    models = json.load(open(args.input)).get("models", [])
    anomalies = audit(models)
    by_rule = Counter(a["rule"] for a in anomalies)
    by_sev = Counter(a["severity"] for a in anomalies)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(models),
        "anomaly_count": len(anomalies),
        "by_severity": dict(by_sev),
        "by_rule": dict(by_rule.most_common()),
        "anomalies": anomalies,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[audit-anomalies] {len(anomalies)} anomalies across {len(models)} models "
          f"(high={by_sev.get('high',0)} medium={by_sev.get('medium',0)} low={by_sev.get('low',0)})")
    for rule, n in by_rule.most_common():
        print(f"   {n:4}  {rule}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
