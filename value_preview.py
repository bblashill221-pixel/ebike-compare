#!/usr/bin/env python3
"""Eye-test the value meter. Prints each (product type x build tier) peer group with its
typical price, then every bike sorted by value_index (typical/price) with its pips + level
+ price -- so you can scan for rankings that look wrong, tweak the VALUE_BANDS / build-grade
constants in analyze.py, rebuild, and re-run.

    python value_preview.py                # all groups
    python value_preview.py --type "Mountain (eMTB)"
    python value_preview.py --anomalies    # only extreme ratios (likely thin-group/mis-tier)

Reads web/public/ebike.json (rebuild first to reflect config changes)."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

PIPS = {"Exceptional": "●●●●", "Outstanding": "●●●○", "Great": "●●○○", "Good": "●○○○"}
PAYLOAD = Path(__file__).parent / "web" / "public" / "ebike.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", help="filter to one product type")
    ap.add_argument("--limit", type=int, default=0, help="max rows per group (0 = all)")
    ap.add_argument("--anomalies", action="store_true",
                    help="only bikes with value_index >=3 or <=0.5 (suspect groups)")
    args = ap.parse_args()

    models = json.loads(PAYLOAD.read_text())["models"]
    groups = defaultdict(list)
    dist = Counter()
    for m in models:
        t = m.get("analysis", {}).get("specs_typed", {})
        lvl = t.get("value_level")
        dist[lvl or "Unrated"] += 1
        tier, typ = t.get("build_tier"), m.get("product_type")
        if lvl and m.get("price"):
            groups[(typ, tier)].append((t.get("value_index"), lvl, m.get("price"),
                                        m.get("brand"), (m.get("model") or "")[:34]))

    total = sum(dist.values())
    print("VALUE LEVEL DISTRIBUTION (target: Exceptional ~15%)")
    for lvl in ("Exceptional", "Outstanding", "Great", "Good", "Unrated"):
        c = dist.get(lvl, 0)
        print(f"  {lvl:12} {c:4}  {100*c/total:4.0f}%")
    print()

    tier_order = {"Premium": 0, "Enhanced": 1, "Standard": 2, "Budget": 3}
    for (typ, tier), rows in sorted(groups.items(),
                                    key=lambda kv: (kv[0][0] or "", tier_order.get(kv[0][1], 9))):
        if args.type and typ != args.type:
            continue
        rows.sort(key=lambda r: -(r[0] or 0))
        med = median([r[2] for r in rows])
        shown = [r for r in rows if not args.anomalies or r[0] >= 3 or r[0] <= 0.5]
        if not shown:
            continue
        print(f"=== {typ}  ·  {tier} build   (n={len(rows)}, typical ${med:,.0f}) ===")
        for idx, lvl, price, brand, name in (shown[:args.limit] if args.limit else shown):
            print(f"   {PIPS[lvl]} {lvl:11} {idx:5.2f}  ${price:>7,.0f}  {brand:11} {name}")
        print()


if __name__ == "__main__":
    main()
