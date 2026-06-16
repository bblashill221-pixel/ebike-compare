#!/usr/bin/env python3
"""One-off: inject current Shopify availability into the existing magicycle data
without a full re-scrape (which would drop the frame-size / accessory enrichments).
Fetches the e-bikes collection feed, builds per-variant `configurations` carrying
`available`, and matches them onto each model by handle. After running, normalize
recognizes a fully sold-out bike (e.g. the Jaguarundi 2.0) as sold out.

(The durable fix is in scrape_magicycle.py, which now emits these configurations on
every scrape; this script just back-fills the current build.)
"""
import json
import urllib.request
from pathlib import Path

HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
F = Path(__file__).parent / "data" / "current" / "magicycle_ebikes.json"


def main():
    d = json.load(open(F))
    base = (d.get("source") or "https://magicyclebike.com").rstrip("/")
    feed = json.load(urllib.request.urlopen(
        urllib.request.Request(f"{base}/collections/e-bikes/products.json?limit=250", headers=HDRS), timeout=30))
    by_handle = {p["handle"]: p for p in feed.get("products", [])}
    for m in d["models"]:
        p = by_handle.get(m.get("handle"))
        if not p:
            continue
        onames = [o.get("name") for o in p.get("options", [])]
        cfgs = []
        for v in p.get("variants", []):
            opts = {}
            for j, nm in enumerate(onames, start=1):
                val = v.get(f"option{j}")
                if nm and val not in (None, "Default Title"):
                    opts[nm] = val
            cfgs.append({"options": opts,
                         "price": float(v["price"]) if v.get("price") else None,
                         "available": bool(v.get("available")), "sku": v.get("sku")})
        m["configurations"] = cfgs
        a = sum(1 for c in cfgs if c["available"])
        print(f"  {m['model'][:38]:40} variants={len(cfgs)} avail={a}{'  SOLD OUT' if a == 0 else ''}")
    F.write_text(json.dumps(d, indent=2, ensure_ascii=False))


main()
