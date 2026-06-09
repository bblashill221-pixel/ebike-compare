#!/usr/bin/env python3
"""
Build the component part catalog from the normalized e-bike data.

parse_components.py already extracts `manufacturer` / `model` from each spec row
during normalization; this step aggregates those parsed parts across the whole
fleet into one deduped catalog keyed by category|manufacturer|model:

    data/component_catalog.json

Each entry records which bikes use the part (usage_count / used_by) plus an
`aftermarket` block ({price_usd, currency, url, checked_at, notes}) meant to be
filled by aftermarket price lookups — part price is a quality signal that feeds
the analysis layer (analyze.py joins the catalog back per bike as
`analysis.component_quality`).

Rebuilds re-derive the fleet usage from scratch but PRESERVE the aftermarket
block of every key, and keep entries that dropped out of the fleet
(usage_count 0) so paid-for lookup data is never lost. The catalog therefore
lives outside data/current/ (which run_scrape.sh archives per build).

Run after normalize.py, before analyze.py (run_scrape.sh wires this).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# spec-field name -> canonical part category (first substring match wins; the
# field name itself is the fallback category).
_CATEGORY_RULES = [
    ("derailleur", ("derailleur",)),
    ("shifter", ("shifter", "shifting", "shift_lever")),
    ("cassette", ("cassette", "freewheel", "cog")),
    ("crankset", ("crank", "chainring", "chainwheel")),
    ("chain", ("chain",)),
    ("brakes", ("brake",)),
    ("fork", ("fork", "suspension")),
    ("motor", ("motor", "drive_unit")),
    ("battery", ("battery",)),
    ("display", ("display",)),
    ("tire", ("tire", "tyre")),
    ("saddle", ("saddle",)),
    ("hub", ("hub",)),
    ("pedals", ("pedal",)),
    ("light", ("light",)),
]

_EMPTY_AFTERMARKET = {"price_usd": None, "currency": "USD", "url": None,
                      "checked_at": None, "notes": None}


def category_of(field: str) -> str:
    low = (field or "").lower()
    for cat, words in _CATEGORY_RULES:
        if any(w in low for w in words):
            return cat
    return low


def component_key(category: str, manufacturer: str, model) -> str:
    return f"{category}|{manufacturer.strip().lower()}|{str(model or '').strip().lower()}"


def iter_components(normalized_model: dict):
    """Yield (key, category, parsed-dict) for every parsed component carrying a
    manufacturer in a normalized model's grouped specs."""
    for group, fields in (normalized_model.get("specs") or {}).items():
        if group == "geometry" or not isinstance(fields, dict):
            continue
        for field, v in fields.items():
            if isinstance(v, dict) and v.get("manufacturer"):
                cat = category_of(field)
                yield component_key(cat, v["manufacturer"], v.get("model")), cat, v


def build_catalog(models: list, previous: dict) -> dict:
    prev_entries = previous.get("components") or {}
    entries: dict = {}
    for m in models:
        for key, cat, part in iter_components(m):
            e = entries.get(key)
            if e is None:
                attrs = {k: v for k, v in part.items()
                         if k not in ("manufacturer", "model", "details") and v not in (None, "")}
                e = entries[key] = {
                    "category": cat,
                    "manufacturer": part["manufacturer"],
                    "model": part.get("model") or None,
                    "attributes": attrs,
                    "sample_details": part.get("details") or None,
                    "usage_count": 0,
                    "used_by": [],
                    "aftermarket": dict(prev_entries.get(key, {}).get("aftermarket")
                                        or _EMPTY_AFTERMARKET),
                }
            e["usage_count"] += 1
            if m["id"] not in e["used_by"]:
                e["used_by"].append(m["id"])
    # keep previously-cataloged parts that fell out of the fleet: their
    # aftermarket lookups may have cost money and the part may come back
    for key, old in prev_entries.items():
        if key not in entries:
            entries[key] = {**old, "usage_count": 0, "used_by": []}
    return dict(sorted(entries.items()))


def main():
    ap = argparse.ArgumentParser(description="Aggregate the fleet's component part catalog.")
    ap.add_argument("-i", "--input", default=str(DATA / "current" / "active" / "ebikes_normalized.json"))
    ap.add_argument("-o", "--output", default=str(DATA / "component_catalog.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    try:
        previous = json.load(open(args.output))
    except FileNotFoundError:
        previous = {}

    components = build_catalog(doc.get("models", []), previous)
    priced = sum(1 for e in components.values()
                 if (e.get("aftermarket") or {}).get("price_usd") is not None)
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "component_count": len(components),
        "priced_count": priced,
        "components": components,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    lookupable = sum(1 for e in components.values() if e.get("model"))
    print(f"Wrote {Path(args.output).name}: {len(components)} parts "
          f"({lookupable} with model numbers, {priced} priced)")


if __name__ == "__main__":
    main()
