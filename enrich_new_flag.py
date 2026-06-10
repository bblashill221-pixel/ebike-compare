#!/usr/bin/env python3
"""
Flag each model "new" only when the brand's own site declares it a new arrival.

Most brands are Shopify; their product feed carries the tags that drive the
storefront's "New" badge (e.g. Aventon's "new" / "homepage_new_arrivals_
collection"). This fetches each brand's <source>/products.json, reads each
product's tags, and sets `is_new` on the matching model (by handle) when a
new-arrival tag is present. Brands without a reachable Shopify feed are left
untouched (is_new stays unset -> false), so "New" never appears unless the site
explicitly says so.

Idempotent (re-sets the same flag); run after the scrapers, before normalize.

Usage:  python enrich_new_flag.py
"""
import glob
import json
import re
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"

_NEW = re.compile(r"new[\s_-]?arrival|just[\s_-]?(?:dropped|launched|released)|^new$", re.I)


def fetch_tags(base: str) -> dict:
    """handle -> [tags] across the store's products.json (paginated)."""
    out: dict = {}
    for page in range(1, 8):
        url = f"{base}/products.json?limit=250&page={page}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = json.load(urllib.request.urlopen(req, timeout=25))
        except Exception:
            break
        prods = data.get("products", [])
        if not prods:
            break
        for p in prods:
            if p.get("handle"):
                out[p["handle"]] = p.get("tags") or []
        if len(prods) < 250:
            break
    return out


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        base = (d.get("source") or "").rstrip("/")
        if not base:
            continue
        tags = fetch_tags(base)
        if not tags:
            continue                              # not Shopify / no reachable feed
        changed = 0
        for m in d.get("models", []):
            handle = (m.get("handle") or "").split("--", 1)[0]
            t = tags.get(handle)
            if t is None:
                continue
            is_new = any(_NEW.search(str(x)) for x in t)
            if m.get("is_new") != is_new:
                m["is_new"] = is_new
                changed += 1
        if changed:
            Path(f).write_text(json.dumps(d, indent=2, ensure_ascii=False))
        n_new = sum(1 for m in d.get("models", []) if m.get("is_new"))
        print(f"{brand:<12} new-arrivals: {n_new:>2}  (matched {sum(1 for m in d.get('models', []) if (m.get('handle') or '').split('--',1)[0] in tags)}/{len(d.get('models', []))})")


if __name__ == "__main__":
    main()
