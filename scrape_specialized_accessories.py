#!/usr/bin/env python3
"""Scrape Specialized's bike-accessory catalog into specialized_ebikes.json's
`available_accessories`, so the detail page can show optional add-ons (Specialized
is a non-Shopify, JS-rendered site, so enrich_shipping_accessories' Shopify-collection
fetch doesn't apply to it).

Targets the ebike-relevant sub-categories under /shop/cycling-gear/bike-accessories
(electric-bike, cargo-bike, commuter utilities, bags, pumps) -- NOT helmets/apparel
/bottles -- and reads each product's name, price and URL from the listing grid.

Usage: python scrape_specialized_accessories.py
"""
import json, re, sys
from pathlib import Path
import scraper_common  # noqa: F401
from playwright.sync_api import sync_playwright

BASE = "https://www.specialized.com"
ROOT = f"{BASE}/us/en/shop/cycling-gear/bike-accessories"
SUBCATS = ["electric-bike-accessories", "cargo-bike-accessories",
           "commuter-utilities", "bike-bags", "bike-pumps"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT = Path(__file__).parent / "data" / "current" / "specialized_ebikes.json"
# guard against apparel/consumables that leak into the grids as cross-sell
_DROP = re.compile(r"helmet|shoe|jersey|\bshort\b|\bbib\b|glove|sock|\bcap\b|vest|"
                   r"jacket|eyewear|glasses|goggle|water bottle\b|hydration", re.I)

_EXTRACT = r"""() => {
  const out = [];
  const PRICE = /\$[\d,]+(?:\.\d{2})?/;
  // one ProductCard article per product; the price lives inside it next to the name
  for (const card of document.querySelectorAll('[class*="ProductCard_productCardWrapper"]')) {
    const a = card.querySelector('a[href*="/p/"]');
    if (!a) continue;
    const href = (a.getAttribute('href') || '').split('?')[0];
    if (!/\/p\/\d+/.test(href)) continue;
    const ct = (card.innerText || '').replace(/\s+/g, ' ').trim();
    const price = (ct.match(PRICE) || [''])[0];
    const name = ct.replace(/\$.*/, '').replace(/\b(Best Seller|New|Sale|Exclusive)\b/gi, '')
                  .replace(/\+\d+\s*colou?rs?/i, '').replace(/\+\d+/, '').replace(/\s+/g, ' ').trim();
    if (!name) continue;
    out.push({ name: name.slice(0, 60), price, href: href.startsWith('http') ? href : location.origin + href });
  }
  return out;
}"""

def main():
    seen, items = set(), []
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": 1400, "height": 1600}, user_agent=UA)
        for sub in SUBCATS:
            try:
                pg.goto(f"{ROOT}/{sub}", wait_until="domcontentloaded", timeout=60000)
                pg.wait_for_timeout(3500)
                for _ in range(14):
                    pg.mouse.wheel(0, 2200); pg.wait_for_timeout(200)
                rows = pg.evaluate(_EXTRACT)
            except Exception as e:
                print(f"  {sub}: ERR {e}", file=sys.stderr); rows = []
            n0 = len(items)
            for r in rows:
                if r["href"] in seen or _DROP.search(r["name"]):
                    continue
                seen.add(r["href"])
                price = None
                if r["price"]:
                    price = float(r["price"].replace("$", "").replace(",", ""))
                items.append({"name": r["name"], "price": price, "regular_price": None,
                              "on_sale": False, "free": False, "url": r["href"]})
            print(f"  {sub:28} +{len(items)-n0}")
        b.close()
    d = json.load(open(OUT))
    d["available_accessories"] = items
    d["available_accessories_count"] = len(items)
    OUT.write_text(json.dumps(d, indent=2, ensure_ascii=False))
    print(f"[specialized-accessories] {len(items)} accessories -> {OUT}")

main()
