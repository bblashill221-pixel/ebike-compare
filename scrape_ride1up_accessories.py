#!/usr/bin/env python3
"""Scrape Ride1Up's accessory catalog into ride1up_ebikes.json's
`available_accessories` (Ride1Up is WooCommerce, not Shopify, so the Shopify
enricher skips it). Accessory slugs come from the /product-category/bike-accessories
and /parts category pages (minus the bike models themselves and non-products);
each product page yields its title and og price.

Usage: python scrape_ride1up_accessories.py
"""
import html, json, re, urllib.request
from pathlib import Path

BASE = "https://ride1up.com"
CATS = ["bike-accessories", "parts"]
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
OUT = Path(__file__).parent / "data" / "current" / "ride1up_ebikes.json"
_SKIP = {"gift-card", "open-box-ebike", "yoast-seo-wordpress"}


def get(url: str) -> str:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=25).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def main():
    d = json.load(open(OUT))
    slugs = []
    for cat in CATS:
        for s in re.findall(r"/product/([a-z0-9-]+)/", get(f"{BASE}/product-category/{cat}/")):
            if s not in _SKIP and s not in slugs:
                slugs.append(s)
    items = []
    for s in slugs:
        h = get(f"{BASE}/product/{s}/")
        if not h:
            continue
        title = (re.search(r'<h1[^>]*class="product_title[^"]*"[^>]*>([^<]+)<', h)
                 or re.search(r'<h1[^>]*>([^<]+)</h1>', h) or [None, None])[1]
        pm = re.search(r'property="product:price:amount"\s+content="([\d.]+)"', h) \
            or re.search(r'"price"\s*:\s*"?([\d.]+)"?', h)
        price = round(float(pm.group(1)), 2) if pm else None
        # bikes cross-link into the accessory categories; they're $700+ while every
        # real accessory is well under that -> a price ceiling cleanly drops them.
        if not title or price is None or price >= 700:
            continue
        items.append({"name": html.unescape(title).strip()[:60], "price": price,
                      "regular_price": None, "on_sale": False, "free": False,
                      "url": f"{BASE}/product/{s}/"})
        print(f"  {title.strip()[:40]:42} ${items[-1]['price']}")
    d["available_accessories"] = items
    d["available_accessories_count"] = len(items)
    OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print(f"[ride1up-accessories] {len(items)} accessories ({sum(1 for x in items if x['price'])} priced) -> {OUT}")


main()
