#!/usr/bin/env python3
"""
Point each tier-split model entry at its own configuration on the brand site.

After expand_tiers.py, sibling entries ("PRODIGY V2 — Belt CVT · Step-Thru")
all share the family's product URL, which lands the shopper on the page's
default configuration. Where the platform supports URL preselection this step
rewrites each tiered entry's `url` to deep-link its cheapest configuration:

  - Shopify brands:  <product url>?variant=<id>  — the id comes from the
    config's `variant_id` (captured by add_configurations.py) or is resolved
    live from the collection feed by SKU when older data lacks it;
  - Ride1Up (WooCommerce):  ?attribute_pa_<option>=<value-slug> for each
    non-color option (color is left to the shopper);
  - everything else (Specialized, Tern, ...) has no URL preselection scheme
    and silently keeps the plain product page. Best effort by design.

Idempotent: existing query strings are stripped before the link is rebuilt.
Run after expand_tiers.py, before normalize.py (run_scrape.sh wires this).
"""
import glob
import json
import re
import urllib.parse
from pathlib import Path

from add_configurations import COLLECTION, fetch_products

HERE = Path(__file__).parent
DATA = HERE / "data"


def cheapest_config(m: dict):
    cfgs = [c for c in m.get("configurations") or [] if isinstance(c, dict)]
    priced = [c for c in cfgs if c.get("price") is not None]
    if priced:
        return min(priced, key=lambda c: c["price"])
    return cfgs[0] if cfgs else None


def base_url(m: dict) -> str:
    return (m.get("url") or "").split("?", 1)[0]


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def shopify_links(d: dict) -> int:
    """url -> url?variant=<id> for tiered models; live SKU lookup as backfill.
    A variant id only preselects on its OWN product page, so SKUs are resolved
    within the model's product (handle before the `--` sibling separator)."""
    prods = None              # lazy: only fetch the feed if some config lacks an id

    def resolve(m, cfg):
        nonlocal prods
        if cfg.get("variant_id"):
            return cfg["variant_id"]
        if not cfg.get("sku"):
            return None
        if prods is None:
            base = (d.get("source") or "").rstrip("/")
            prods = fetch_products(base, COLLECTION[d["_brand"]])
        handle = (m.get("handle") or "").split("--", 1)[0]
        for v in (prods.get(handle) or {}).get("variants", []):
            if v.get("sku") == cfg["sku"] and v.get("id"):
                return v["id"]
        return None

    n = 0
    for m in d.get("models", []):
        if not m.get("tier"):
            continue
        cfg = cheapest_config(m)
        vid = resolve(m, cfg) if cfg else None
        if vid:
            m["url"] = f"{base_url(m)}?variant={vid}"
            n += 1
    return n


def ride1up_links(d: dict) -> int:
    """WooCommerce preselection from the entry's non-color option values."""
    n = 0
    for m in d.get("models", []):
        if not m.get("tier"):
            continue
        cfg = cheapest_config(m)
        opts = {k: v for k, v in ((cfg or {}).get("options") or {}).items()
                if "color" not in k.lower() and v}
        if opts:
            q = urllib.parse.urlencode(
                {f"attribute_pa_{_slug(k)}": _slug(str(v)) for k, v in sorted(opts.items())})
            m["url"] = f"{base_url(m)}?{q}"
            n += 1
    return n


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        d["_brand"] = brand
        before = json.dumps(d.get("models", []), sort_keys=True)
        if brand in COLLECTION:
            n = shopify_links(d)
        elif brand == "ride1up":
            n = ride1up_links(d)
        else:
            continue
        d.pop("_brand", None)
        if json.dumps(d.get("models", []), sort_keys=True) != before:
            json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        if n:
            print(f"{brand:<10} deep-linked {n} tiered entries")


if __name__ == "__main__":
    main()
