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

# Brands whose PDPs don't surface warranty text in the page body (verified on
# the brand's own warranty page/site).
KNOWN_FALLBACK = {"lectric": "1-Year Warranty"}

HERE = Path(__file__).parent
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
