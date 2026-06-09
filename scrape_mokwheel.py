#!/usr/bin/env python3
"""
Mokwheel e-bike spec scraper.

Mokwheel is a Shopify store. Models are discovered from the electric-bikes
collection feed; each product page is rendered with Playwright to extract the
"keynote specification" section. Colors are emitted as {name, hex, image}:

  * name  -- the Shopify "Color" variant option value,
  * image -- that color's variant photo (from the catalog feed),
  * hex   -- sampled from the swatch chip image's centre pixel (Mokwheel uses
             image swatches, so this is a best-effort representative colour).

Output JSON mirrors the Aventon/Lectric scrapers.

Usage:
    python scrape_mokwheel.py                  # all models -> mokwheel_ebikes.json
    python scrape_mokwheel.py --limit 3        # quick test (first 3 models)
    python scrape_mokwheel.py -o out.json      # custom output path
    python scrape_mokwheel.py --concurrency 2  # parallel product pages
    python scrape_mokwheel.py --headed         # watch the browser
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


from scraper_common import fetch_json  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

from bike_taxonomy import classify_product_types

BASE = "https://www.mokwheel.com"
LOGO = "https://www.mokwheel.com/cdn/shop/files/mokwheel_logo.png?v=1737345448"
COLLECTION = "electric-bikes"


# ----------------------------- catalog discovery -----------------------------


def build_colors(color_values, color_idx, variants, fallback_image):
    """[{name, hex(None), image}] -- hex is filled from the PDP swatches later."""
    colors = []
    for name in color_values:
        img = None
        if color_idx is not None:
            for v in variants:
                if v.get(f"option{color_idx}") == name:
                    fi = v.get("featured_image")
                    if fi and fi.get("src"):
                        img = fi["src"]
                        break
        colors.append({"name": name, "hex": None, "swatch_image": None,
                       "image": img or fallback_image})
    return colors


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        variants = p.get("variants", [])
        prices = [float(v["price"]) for v in variants if v.get("price")]
        images = [img.get("src") for img in p.get("images", []) if img.get("src")]
        fallback = images[0] if images else None

        options, color_values, color_idx = {}, [], None
        for i, o in enumerate(p.get("options", [])):
            if not o.get("name"):
                continue
            if o["name"].lower().startswith("color"):
                color_values = o.get("values", [])
                color_idx = i + 1
            else:
                options[o["name"]] = o.get("values", [])
        options["colors"] = build_colors(color_values, color_idx, variants, fallback)

        models.append({
            "model": p.get("title"),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or [])),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
        })
    return models


# ------------------------------ page extraction ------------------------------

# The keynote spec section mixes two row markups across its tabs:
#   Geometry:  <div><span>Name</span><span>Value</span></div>
#   Technical: <div><b>Name</b><span>Value</span></div>
# A generic scan over the section handles both.
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    // Scan the whole document, not just the keynote spec section: spec rows for
    // some models live outside .alp-keynote-specification. The per-row guards
    // below (name != value, length caps, dedupe) reject unrelated divs.
    const sec = document.body;
    const out = [], seen = new Set();
    for (const div of sec.querySelectorAll('div')) {
        const kids = [...div.children];
        const b = kids.find(k => k.tagName === 'B');
        const spans = kids.filter(k => k.tagName === 'SPAN');
        let name = null, value = null;
        if (b && spans.length >= 1) { name = norm(b.innerText); value = norm(spans[0].innerText); }
        else if (spans.length === 2 && kids.length === 2) {
            name = norm(spans[0].innerText); value = norm(spans[1].innerText);
        }
        if (name && value && name !== value && name.length <= 40 &&
            value.length <= 200 && !seen.has(name)) {
            seen.add(name);
            out.push([name, value]);
        }
    }
    return out;
}"""

# Swatch chips are same-origin background images, so sample the centre pixel.
JS_SWATCH_HEX = r"""async () => {
    const toHex = (r, g, b) =>
        '#' + [r, g, b].map(x => x.toString(16).padStart(2, '0')).join('');
    const out = {};
    for (const el of document.querySelectorAll('.alp-colors-swatch-i')) {
        const name = el.getAttribute('data-value');
        if (!name) continue;
        const chip = el.querySelector('[class*=alp-color-]') || el;
        const bi = getComputedStyle(chip).backgroundImage;
        const m = bi && bi.match(/url\("?(.*?)"?\)/);
        if (!m) { out[name] = {hex: null, swatch_image: null}; continue; }
        const entry = {hex: null, swatch_image: m[1]};
        try {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.src = m[1];
            await img.decode();
            const c = document.createElement('canvas');
            c.width = img.naturalWidth; c.height = img.naturalHeight;
            const ctx = c.getContext('2d');
            ctx.drawImage(img, 0, 0);
            const d = ctx.getImageData(Math.floor(c.width / 2), Math.floor(c.height / 2), 1, 1).data;
            entry.hex = toHex(d[0], d[1], d[2]);
        } catch (e) {}
        out[name] = entry;
    }
    return out;
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
            for _ in range(18):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            try:
                await page.wait_for_selector(".alp-keynote-specification, .Sp_alp_new, .Sp_tech",
                                             state="attached", timeout=20000)
            except Exception:
                pass
            pairs = []
            for _ in range(20):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            swatch_hex = await page.evaluate(JS_SWATCH_HEX)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

            for c in result["options"].get("colors", []):
                entry = swatch_hex.get(c["name"])
                if entry:
                    if entry.get("hex"):
                        c["hex"] = entry["hex"]
                    if entry.get("swatch_image"):
                        c["swatch_image"] = entry["swatch_image"]
                # swatch_image is a fallback only: drop it when a hex is known.
                if c.get("hex"):
                    c["swatch_image"] = None

            all_specs = {}
            for label, value in pairs:
                key = " ".join(label.split())
                all_specs[key] = value

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
            ncol = len(r["options"].get("colors", []))
            print(f"    - {r['model'][:30]:<30} {r['spec_count']:>3} specs  "
                  f"{ncol} colors  [{status}]", file=sys.stderr)
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
    ap = argparse.ArgumentParser(description="Scrape Mokwheel e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/mokwheel_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Parallel pages. Heavy PDPs hydrate unreliably in "
                         "parallel; default 1 (sequential) is the most reliable.")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
