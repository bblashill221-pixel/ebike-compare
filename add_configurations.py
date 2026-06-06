#!/usr/bin/env python3
"""
Give every configuration (variant) its own price.

For the Shopify brands, fetch the collection's products.json and attach a
`configurations` list to each model: one entry per variant with its option
combination and price. Brands whose scraper already builds per-config prices
(Lectric, Ride1Up, Specialized) are left as-is.

Run after the scrapers (the wrapper calls it automatically).
"""
import glob
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# brand -> e-bike collection handle (Shopify brands only).
COLLECTION = {
    "aventon": "ebikes", "velotric": "electric-bikes", "heybike": "electric-bike",
    "mokwheel": "electric-bikes", "himiway": "ebikes", "euphree": "electric-bikes",
    "vvolt": "e-bikes", "evelo": "evelo-bikes", "blix": "all",
    "monarc": "marker-bikes", "velowave": "all-ebikes",
}
SKIP = {"lectric", "ride1up", "specialized"}  # already have per-config prices


def fetch_products(base: str, handle: str) -> dict:
    url = f"{base}/collections/{handle}/products.json?limit=250"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception:
        return {}
    return {p["handle"]: p for p in data.get("products", [])}


def configs_for(product: dict) -> list[dict]:
    opt_names = [o.get("name") for o in product.get("options", [])]
    out = []
    for v in product.get("variants", []):
        opts = {}
        for i, name in enumerate(opt_names, start=1):
            val = v.get(f"option{i}")
            if name and val and val != "Default Title":
                opts[name] = val
        price = float(v["price"]) if v.get("price") else None
        out.append({"options": opts, "price": price, "sku": v.get("sku"),
                    "available": v.get("available")})
    return out


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        if brand in SKIP or brand not in COLLECTION:
            continue
        d = json.load(open(f))
        base = (d.get("source") or "").rstrip("/")
        prods = fetch_products(base, COLLECTION[brand])
        n = 0
        for m in d.get("models", []):
            p = prods.get(m.get("handle"))
            if not p:
                continue
            m["configurations"] = configs_for(p)
            if len(m["configurations"]) > 1:
                n += 1
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        print(f"{brand:<10} attached configurations ({n} models have >1 priced config)")


if __name__ == "__main__":
    main()
