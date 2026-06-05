#!/usr/bin/env python3
"""
Capture each bike's regular (pre-discount) price so the site can show discounts.

Shopify exposes a variant's list price as `compare_at_price` (vs the current
`price`). This post-processor fetches each Shopify brand's catalog feed and writes
`regular_price` onto every model whose lowest-priced variant is on sale (matched by
Shopify `handle`). normalize.py turns that into a `pricing` block with `on_sale`,
`discount_amount` and `discount_pct`.

Brands on other platforms (Ride1Up/Woo, Specialized, Tern) don't expose a uniform
compare-at price here and are skipped (no `regular_price` -> `on_sale: false`).
Runs after the scrapers (the wrapper calls it); one network fetch per brand.
"""
import glob
import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# brand -> (base, collection) for the Shopify catalogs (mirrors each scraper).
SHOPIFY = {
    "aventon": ("https://www.aventon.com", "ebikes"),
    "lectric": ("https://lectricebikes.com", "ebikes"),
    "velotric": ("https://www.velotricbike.com", "electric-bikes"),
    "heybike": ("https://www.heybike.com", "electric-bike"),
    "mokwheel": ("https://www.mokwheel.com", "electric-bikes"),
    "evelo": ("https://www.evelo.com", "evelo-bikes"),
    "himiway": ("https://himiwaybike.com", "ebikes"),
    "euphree": ("https://euphree.com", "electric-bikes"),
    "vvolt": ("https://vvolt.com", "e-bikes"),
    "blix": ("https://blixbike.com", "all"),
}


def sale_map(base: str, collection: str) -> dict:
    """handle -> (price, regular) for products whose cheapest variant is on sale."""
    out, page = {}, 1
    while True:
        url = f"{base}/collections/{collection}/products.json?limit=250&page={page}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            products = json.load(resp).get("products", [])
        if not products:
            break
        for p in products:
            variants = [v for v in p.get("variants", []) if v.get("price")]
            if not variants:
                continue
            cheapest = min(variants, key=lambda v: float(v["price"]))
            price = float(cheapest["price"])
            cmp_at = cheapest.get("compare_at_price")
            cmp_at = float(cmp_at) if cmp_at else None
            if cmp_at and cmp_at > price:
                out[p.get("handle")] = (price, round(cmp_at, 2))
        if len(products) < 250:
            break
        page += 1
    return out


def _handles(m: dict) -> list:
    """Every Shopify handle a model might map to: its own handle plus the handles
    embedded in its config/product URLs (covers Lectric's family models)."""
    hs = [m["handle"]] if m.get("handle") else []
    urls = list(m.get("urls") or [])
    urls += [c.get("url") for c in (m.get("configs") or []) if c.get("url")]
    for u in urls:
        hs.append(u.rstrip("/").rsplit("/", 1)[-1])
    return hs


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        if brand not in SHOPIFY:
            continue
        try:
            smap = sale_map(*SHOPIFY[brand])
        except Exception as e:  # noqa: BLE001 -- network hiccup shouldn't break the run
            print(f"{brand:<10} skipped ({type(e).__name__}: {e})")
            continue
        d = json.load(open(f))
        on_sale = 0
        for m in d.get("models", []):
            matches = [smap[h] for h in _handles(m) if h in smap]
            if matches:
                m["regular_price"] = min(matches, key=lambda pr: pr[0])[1]  # cheapest match
                on_sale += 1
            else:
                m.pop("regular_price", None)
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        print(f"{brand:<10} on sale: {on_sale}/{len(d.get('models', []))}")


if __name__ == "__main__":
    main()
