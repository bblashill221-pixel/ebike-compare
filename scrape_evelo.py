#!/usr/bin/env python3
"""
EVELO e-bike spec scraper.

EVELO is a Shopify store. Models are discovered from the evelo-bikes collection
feed; each product page is rendered with Playwright to extract the spec list
(`.spec-item` blocks: an <h4> label + a `.copy` value).

EVELO sells a single configuration per model (no colour variants), so
`options.colors` holds one "Standard" entry carrying the bike's product image;
`hex` / `swatch_image` are null. Output JSON mirrors the other scrapers.

Usage:
    python scrape_evelo.py                  # all models -> evelo_ebikes.json
    python scrape_evelo.py --limit 2        # quick test (first 2 models)
    python scrape_evelo.py -o out.json      # custom output path
    python scrape_evelo.py --concurrency 2  # parallel product pages
    python scrape_evelo.py --headed         # watch the browser
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


from scraper_common import fetch_json  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

from bike_taxonomy import classify_product_types

BASE = "https://www.evelo.com"
LOGO = "assets/logos/evelo.svg"   # self-hosted wordmark (EVELO renders its logo as inline SVG; no CDN asset)
COLLECTION = "evelo-bikes"


# ----------------------------- catalog discovery -----------------------------


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        variants = p.get("variants", [])
        prices = [float(v["price"]) for v in variants if v.get("price")]
        images = [img.get("src") for img in p.get("images", []) if img.get("src")]
        # Single configuration -> one "Standard" colour carrying the product image.
        colors = [{"name": "Standard", "hex": None, "swatch_image": None,
                   "image": images[0] if images else None}]
        models.append({
            "model": p.get("title"),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": {"colors": colors},
        })
    return models


# ------------------------------ page extraction ------------------------------

JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [];
    for (const it of document.querySelectorAll('.spec-item')) {
        const h = it.querySelector('h4, h5, h3, .h6');
        const copy = it.querySelector('.copy');
        const label = norm(h ? h.innerText : '');
        const value = norm(copy ? copy.innerText : '');
        // Real spec labels are short; this skips the marketing intro blurb.
        if (label && value && label !== value && label.length <= 40) out.push([label, value]);
    }
    return out;
}"""

# EVELO publishes the bike's range as a "Battery" metafield pill in the main-product
# feature strip (`.metafields-wrapper`) -- e.g. title "Battery" / text "60 Miles" --
# NOT in the .spec-item table, so the spec scrape misses it. The same markup repeats
# in the "you may also like" carousel further down; the main product's strip is the
# FIRST .metafields-wrapper in the DOM. Return its title/text pairs.
JS_METAFIELDS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const wrap = document.querySelector('.metafields-wrapper');
    if (!wrap) return [];
    const out = [];
    for (const mf of wrap.querySelectorAll('.metafield')) {
        const t = norm(mf.querySelector('.metafield-title') ? mf.querySelector('.metafield-title').textContent : '');
        const v = norm(mf.querySelector('.metafield-text') ? mf.querySelector('.metafield-text').textContent : '');
        if (t && v) out.push([t, v]);
    }
    return out;
}"""

JS_PRICE = r"""() => {
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
        let d; try { d = JSON.parse(s.textContent); } catch (e) { continue; }
        const objs = Array.isArray(d) ? d : (d['@graph'] || [d]);
        for (const o of objs) {
            if (o && o['@type'] === 'Product') {
                let off = o.offers;
                if (Array.isArray(off)) off = off[0];
                if (off && off.price != null) return parseFloat(off.price);
            }
        }
    }
    return null;
}"""


async def scrape_model(context, model: dict, retries: int = 3) -> dict:
    result = dict(model)
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            for _ in range(16):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            try:
                await page.wait_for_selector(".spec-item", state="attached", timeout=20000)
            except Exception:
                pass
            pairs = []
            for _ in range(20):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            price = await page.evaluate(JS_PRICE)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            metafields = await page.evaluate(JS_METAFIELDS)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

            if price is not None:
                result["price_from"] = price

            all_specs = {}
            for label, value in pairs:
                key = " ".join(label.split())
                if key in all_specs:
                    continue
                all_specs[key] = value

            # EVELO's "Battery" feature pill is the bike's range ("60 Miles"); surface
            # it as a Range spec row (the detailed "Battery" 48V/15AH row stays intact).
            for label, value in (metafields or []):
                if label.strip().lower() == "battery" and re.search(r"\d+\s*mile", value, re.I):
                    all_specs.setdefault("Range", value)

            result["specs"] = {"all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result["specs"] = {"all": {}}
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    print(f"[*] Discovering models from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} e-bike model(s).", file=sys.stderr)

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headed, args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": 1366, "height": 1000},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )

        async def worker(m):
            async with sem:
                r = await scrape_model(context, m)
            status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
            print(f"    - {r['model'][:34]:<34} {r['spec_count']:>3} specs  [{status}]",
                  file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r["model"] or "")
    out = {
        "source": BASE, "logo": LOGO,
        "collection": COLLECTION,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape EVELO e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/evelo_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
