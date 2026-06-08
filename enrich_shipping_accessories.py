#!/usr/bin/env python3
"""
Enrich each brand's scraped JSON with shipping + accessories.

Per model:
  * shipping        -- {"cost": 0, "free": true}. These DTC e-bike brands ship
                       complete bikes free to the continental US; non-free cases
                       can be overridden per brand in NON_FREE_SHIPPING.
  * free_accessories -- the $0 items bundled with the bike, derived from spec
                       rows whose value says "included" (rack, fenders, lights…).

Per file (brand-level, to avoid duplicating a big catalog on every model):
  * available_accessories -- the brand's paid accessory catalog
                       [{name, price, free}] from its Shopify accessories
                       collection (free == price 0).

Run after the scrapers (the wrapper calls it automatically).
"""
import glob
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# brand -> Shopify accessories collection handle (None = not collected here).
ACC_COLLECTION = {
    "aventon": "all-accessories", "lectric": "accessories", "velotric": "accessories",
    "heybike": "accessories", "mokwheel": "all-accessories", "himiway": "accessories",
    "vvolt": "accessories", "evelo": "must-have-accessories", "blix": "accessories",
    "euphree": None, "ride1up": None, "specialized": None,
    "wired": None, "magician": None,
}
# Brands/models that are not free shipping (none known; placeholder for overrides).
NON_FREE_SHIPPING: dict = {}

INCLUDED_RE = re.compile(r"\b(included|comes with|standard|integrated)\b", re.I)
NOT_INCLUDED_RE = re.compile(r"not included|sold separately|optional|n/?a\b", re.I)


def fetch_accessories(base: str, handle: str) -> list[dict]:
    url = f"{base}/collections/{handle}/products.json?limit=250"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception:
        return []
    out = []
    for p in data.get("products", []):
        prices = [float(v["price"]) for v in p.get("variants", []) if v.get("price")]
        price = min(prices) if prices else None
        out.append({
            "name": re.sub(r"<[^>]+>", "", p.get("title", "")).strip(),
            "price": price,
            "free": price == 0,
            "url": f"{base}/products/{p.get('handle')}",
        })
    return out


def free_accessories_from_specs(model: dict) -> list[dict]:
    """$0 bundled accessories: spec rows whose value indicates 'included'."""
    specs = (model.get("specs") or {}).get("all", {}) or {}
    ACC = ("rack", "fender", "light", "kickstand", "horn", "bell", "mirror",
           "pump", "lock", "bag", "basket", "phone", "mount", "bottle")
    out, seen = [], set()
    for label, value in specs.items():
        low_l, low_v = label.lower(), str(value).lower()
        if not any(a in low_l for a in ACC):
            continue
        if INCLUDED_RE.search(low_v) and not NOT_INCLUDED_RE.search(low_v):
            key = label.strip().title()
            if key not in seen:
                seen.add(key)
                out.append({"name": key, "price": 0, "free": True, "detail": value})
    return out


def main():
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        base = (d.get("source") or "").rstrip("/")
        handle = ACC_COLLECTION.get(brand)
        catalog = fetch_accessories(base, handle) if handle else []
        d["available_accessories"] = catalog
        d["available_accessories_count"] = len(catalog)
        for m in d.get("models", []):
            brand_override = NON_FREE_SHIPPING.get(brand)
            # A scraper that determined shipping from the site (e.g. WIRED's flat
            # $275 fee) wins; otherwise a brand override, else the DTC free default.
            scraped = m.get("shipping") if (m.get("shipping") or {}).get("free") is not None else None
            m["shipping"] = scraped or brand_override or {"cost": 0, "free": True}
            m["free_accessories"] = free_accessories_from_specs(m)
        json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
        nfree = sum(len(m.get("free_accessories", [])) for m in d.get("models", []))
        print(f"{brand:<12} catalog={len(catalog):>3}  free-included spec rows across models={nfree}")


if __name__ == "__main__":
    main()
