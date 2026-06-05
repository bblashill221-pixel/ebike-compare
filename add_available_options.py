#!/usr/bin/env python3
"""
Build a consolidated `available_options` list for every bike -- all selectable
options, whether free or paid.

For each model it groups:
  * variant options (Size, Color, Battery, Frame, Version, Type, …) with each
    choice's price and price_delta vs the cheapest configuration (free == no
    upcharge), computed from the per-config prices, and
  * accessory options -- the $0 bundled ones (free) and any paid add-ons.

Each choice carries `free` (true when it adds no cost). Runs as a post-process
(the wrapper calls it automatically); no re-scrape needed.
"""
import glob
import json
from math import inf
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"


def base_price(m: dict) -> float | None:
    cfgs = [c["price"] for c in (m.get("configurations") or []) if c.get("price") is not None]
    if cfgs:
        return min(cfgs)
    if m.get("price_from") is not None:
        return m["price_from"]
    pr = m.get("price_range") or {}
    return pr.get("min") or pr.get("max") or m.get("price")


def variant_groups(m: dict, base: float | None) -> list[dict]:
    configs = m.get("configurations") or []
    groups = []
    if configs:
        keys = []
        for c in configs:
            for k in (c.get("options") or {}):
                if k not in keys:
                    keys.append(k)
        for key in keys:
            cheapest = {}
            for c in configs:
                v = (c.get("options") or {}).get(key)
                p = c.get("price")
                if v is None or p is None:
                    continue
                cheapest[v] = min(cheapest.get(v, inf), p)
            choices = []
            for v, p in cheapest.items():
                delta = round(p - base, 2) if base is not None else None
                choices.append({"value": v, "price": p, "price_delta": delta,
                                "free": delta == 0})
            if choices:
                groups.append({"group": key, "type": "variant", "choices": choices})
        if groups:
            return groups
    # No per-config option groups: list the option values from the options field
    # (all selectable; configs without option keys, e.g. Specialized offers).
    for key, vals in (m.get("options") or {}).items():
        if key == "colors":
            vals = [c.get("name") for c in vals if c.get("name")]
        if isinstance(vals, list) and vals:
            groups.append({"group": key, "type": "variant",
                           "choices": [{"value": v, "free": True} for v in vals]})
    return groups


def accessory_groups(m: dict) -> list[dict]:
    groups = []
    free = m.get("free_accessories") or []
    if free:
        groups.append({"group": "Included accessories", "type": "accessory",
                       "choices": [{"value": a.get("name"), "price": 0, "free": True}
                                   for a in free]})
    addons = (m.get("accessories") or {}).get("add_ons") or []
    if addons:
        groups.append({"group": "Add-on accessories", "type": "accessory",
                       "choices": [{"value": a.get("name"), "price": a.get("price"),
                                    "free": a.get("price") in (0, None)} for a in addons]})
    return groups


def is_meaningful(group: dict) -> bool:
    """Keep only real options under the model. Color is an option ONLY when a
    choice raises the price; a single forced choice (e.g. 'One Size') isn't an
    option. Accessory groups are always kept."""
    if group.get("type") != "variant":
        return True
    choices = group.get("choices") or []
    has_upcharge = any((c.get("price_delta") or 0) > 0 for c in choices)
    if group.get("group", "").lower() in ("color", "colors"):
        return has_upcharge
    return len(choices) > 1 or has_upcharge


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        d = json.load(open(f))
        for m in d.get("models", []):
            base = base_price(m)
            opts = variant_groups(m, base) + accessory_groups(m)
            m["available_options"] = [g for g in opts if is_meaningful(g)]
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        ms = d.get("models", [])
        avg = (sum(len(m.get("available_options", [])) for m in ms) / len(ms)) if ms else 0
        print(f"{Path(f).stem.replace('_ebikes',''):<10} avg option groups/model = {avg:.1f}")


if __name__ == "__main__":
    main()
