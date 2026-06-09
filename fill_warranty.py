#!/usr/bin/env python3
"""
Fill in missing per-model warranty after scraping.

Warranty is a brand-level policy, but only some PDPs surface the text. This
propagates each brand's most-common extracted warranty to its models that are
missing one, and applies a small known-fallback for brands whose PDPs never
expose it. Run after the scrapers (the wrapper calls it automatically).
"""
import glob
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent

# Brands whose PDPs don't surface warranty text in the page body, but whose
# dedicated warranty page does (the whole-bike / original-owner term, not the
# longer battery/frame component tiers). Curated as data so terms can be edited
# without code changes; lives in data/curated/ so it survives daily re-scrapes.
try:
    KNOWN_FALLBACK = json.loads(
        (HERE / "data" / "curated" / "warranty_fallback.json").read_text())
except (FileNotFoundError, ValueError):
    KNOWN_FALLBACK = {}
DATA = HERE / "data"
for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
    brand = Path(f).stem.replace("_ebikes", "")
    d = json.load(open(f))
    models = d.get("models", [])
    vals = [m.get("warranty") for m in models if m.get("warranty")]
    modal = Counter(vals).most_common(1)[0][0] if vals else KNOWN_FALLBACK.get(brand)
    if not modal:
        continue
    filled = 0
    for m in models:
        if not m.get("warranty"):
            m["warranty"] = modal
            filled += 1
    if filled:
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
    print(f"{brand}: warranty {sum(1 for m in models if m.get('warranty'))}/{len(models)} "
          f"(modal {modal!r}, filled {filled})")
