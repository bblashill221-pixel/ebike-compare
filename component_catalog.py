#!/usr/bin/env python3
"""
Build the component part catalog from the normalized e-bike data.

parse_components.py already extracts `manufacturer` / `model` from each spec row
during normalization; this step aggregates those parsed parts across the whole
fleet into one deduped catalog keyed by category|manufacturer|model:

    data/component_catalog.json

Each entry records which bikes use the part (usage_count / used_by) plus an
`aftermarket` block meant to be filled by resolve_component_prices.py with TWO
independent prices — `retail_usd` (aftermarket street/replacement value) and
`wholesale_usd` (OEM cost) — each with its source + url, a `method`
(model_lookup / oem_range_by_spec / spec_heuristic) and a `checked_at` stamp.
Both are quality signals that feed the analysis layer (analyze.py joins the
catalog back per bike as two roll-ups under `analysis.component_quality`).

For parts with no model number, `spec_class` carries a stable text class
(e.g. "48V 20Ah ebike battery") that the resolver prices against an OEM
marketplace range.

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

_EMPTY_AFTERMARKET = {
    "retail_usd": None, "retail_url": None, "retail_source": None,
    "wholesale_usd": None, "wholesale_url": None, "wholesale_source": None,
    "currency": "USD", "method": None, "checked_at": None, "notes": None,
}
# Legacy single-price keys carried by older catalogs; folded into retail_usd on
# rebuild so already-paid-for lookups are never lost.
_LEGACY_PRICE_KEYS = ("price_usd", "url")


def _migrate_aftermarket(old: dict | None) -> dict:
    """Carry forward a preserved aftermarket block, upgrading the old
    single-price shape ({price_usd, url, ...}) into the dual-price shape."""
    block = dict(_EMPTY_AFTERMARKET)
    if not old:
        return block
    for k in block:
        if old.get(k) is not None:
            block[k] = old[k]
    if block["retail_usd"] is None and old.get("price_usd") is not None:
        block["retail_usd"] = old["price_usd"]
        block["retail_url"] = old.get("url")
        block["method"] = old.get("method") or "model_lookup"
    return block


def category_of(field: str) -> str:
    low = (field or "").lower()
    for cat, words in _CATEGORY_RULES:
        if any(w in low for w in words):
            return cat
    return low


# Attribute -> spec-class templates for OEM range-by-spec pricing of parts that
# carry no model number. First template whose referenced attrs are all present
# wins; falls back to the bare category.
def spec_class(category: str, attrs: dict) -> str:
    a = attrs or {}

    def has(*ks):
        return all(a.get(k) not in (None, "") for k in ks)

    if category == "battery":
        if has("voltage_v", "amphours_ah"):
            return f"{a['voltage_v']}V {a['amphours_ah']}Ah ebike battery"
        if has("capacity_wh"):
            return f"{a['capacity_wh']}Wh ebike battery"
    if category == "motor":
        place = a.get("placement")
        kind = "mid-drive" if place == "mid" else "hub" if place == "hub" else ""
        if has("power_w"):
            return f"{a['power_w']}W {kind} ebike motor".replace("  ", " ").strip()
    if category == "display" and has("type"):
        return f"ebike {a['type']} display"
    if category == "brakes":
        act = a.get("actuation") or ""
        kind = a.get("kind") or "disc"
        if act or kind:
            return f"ebike {act} {kind} brake".replace("  ", " ").strip()
    if category == "tire" and has("diameter_in", "width_in"):
        return f'{a["diameter_in"]}x{a["width_in"]} ebike tire'
    if category == "fork":
        t = a.get("type")
        if t and has("travel_mm"):
            return f"ebike {t} fork {a['travel_mm']}mm"
        if t:
            return f"ebike {t} fork"
    if category == "charger" and has("output_v", "amps_a"):
        return f"{a['output_v']}V {a['amps_a']}A ebike charger"
    return f"ebike {category}"


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
                model = part.get("model") or None
                e = entries[key] = {
                    "category": cat,
                    "manufacturer": part["manufacturer"],
                    "model": model,
                    "attributes": attrs,
                    # text class used to price model-less parts against an OEM range
                    "spec_class": None if model else spec_class(cat, attrs),
                    "sample_details": part.get("details") or None,
                    "usage_count": 0,
                    "used_by": [],
                    "aftermarket": _migrate_aftermarket(prev_entries.get(key, {}).get("aftermarket")),
                }
            e["usage_count"] += 1
            if m["id"] not in e["used_by"]:
                e["used_by"].append(m["id"])
    # keep previously-cataloged parts that fell out of the fleet: their
    # aftermarket lookups may have cost money and the part may come back
    for key, old in prev_entries.items():
        if key not in entries:
            entries[key] = {**old, "usage_count": 0, "used_by": [],
                            "aftermarket": _migrate_aftermarket(old.get("aftermarket"))}
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
                 if (e.get("aftermarket") or {}).get("retail_usd") is not None
                 or (e.get("aftermarket") or {}).get("wholesale_usd") is not None)
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
