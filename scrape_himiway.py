#!/usr/bin/env python3
"""
Himiway e-bike spec scraper (Shopify).

Models come from the `ebikes` collection feed; each product page is rendered with
Playwright to read the `.spec-column` rows (a label + value). Colors are emitted
as {name, hex, swatch_image, image}; `swatch_image` is only set when no `hex` is
found. Output mirrors the other scrapers.

Usage:
    python scrape_himiway.py [-o out.json] [--limit N] [--concurrency N] [--headed]
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

from bike_taxonomy import classify_product_types

BASE = "https://himiwaybike.com"
LOGO = "https://himiwaybike.com/cdn/shop/files/Logo_0f842c6f-da81-478d-9c7e-4b96492f9009.svg?v=1695112798&width=400"
COLLECTION = "ebikes"


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
            "model": clean_title(p.get("title")),
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


JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [], seen = new Set();
    for (const col of document.querySelectorAll('.spec-column')) {
        const label = norm(col.querySelector('.font-semi-bold')?.textContent);
        const value = norm(col.querySelector('.text-color-body')?.textContent);
        if (label && value && !seen.has(label)) { seen.add(label); out.push([label, value]); }
    }
    return out;
}"""

# Key-spec "highlights" grid: each .column holds a big value (h5/.text-2xl) above a
# subtext label, e.g. "Max Motor Torque" -> "86Nm". These sit OUTSIDE the
# .spec-column table, so JS_SPECS misses them — Himiway lists torque only here on
# several models (C5, etc.). Merged in as a fallback (never overwriting the table).
JS_HIGHLIGHTS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [];
    for (const col of document.querySelectorAll('.column')) {
        const value = norm(col.querySelector('h5, .text-2xl')?.textContent);
        const label = norm(col.querySelector('.text-color-subtext')?.textContent);
        if (label && value) out.push([label, value]);
    }
    return out;
}"""

# name -> {hex, swatch_image} from the colour radio swatches.
JS_SWATCHES = r"""() => {
    const rgb2hex = s => {
        const m = s && s.match(/\d+/g);
        return (m && m.length >= 3)
            ? '#' + m.slice(0,3).map(x => (+x).toString(16).padStart(2,'0')).join('') : null;
    };
    const out = {};
    for (const el of document.querySelectorAll('.product-option--swatch')) {
        const inp = el.querySelector('input');
        const name = inp ? inp.value : null;
        if (!name) continue;
        let hex = null, img = null;
        for (const d of [el, ...el.querySelectorAll('*')]) {
            const cs = getComputedStyle(d);
            if (!hex && cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)')
                hex = rgb2hex(cs.backgroundColor);
            const bi = cs.backgroundImage;
            if (!img && bi && bi !== 'none' && !/assets\/filt/.test(bi)) {
                const m = bi.match(/url\("?(.*?)"?\)/);
                if (m) img = m[1];
            }
        }
        out[name] = {hex, swatch_image: img};
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
            for _ in range(16):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            try:
                await page.wait_for_selector(".spec-column", state="attached", timeout=20000)
            except Exception:
                pass
            pairs = []
            for _ in range(20):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            highlights = await page.evaluate(JS_HIGHLIGHTS)
            swatches = await page.evaluate(JS_SWATCHES)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

            for c in result["options"].get("colors", []):
                entry = swatches.get(c["name"])
                if entry:
                    if entry.get("hex"):
                        c["hex"] = entry["hex"]
                    elif entry.get("swatch_image"):
                        c["swatch_image"] = entry["swatch_image"]
                if c.get("hex"):
                    c["swatch_image"] = None  # swatch_image is a fallback only

            all_specs = {}
            for label, value in pairs:
                key = " ".join(label.split())
                all_specs[key] = value
            # Fold in highlight-grid stats (Max Motor Torque, etc.) the main table
            # omits, without clobbering it. Skip prices and sentence-like labels
            # (taglines) that share the same markup.
            for label, value in highlights:
                key = " ".join(label.split())
                if key in all_specs or "$" in value or len(key) > 40:
                    continue
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
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"))

        async def worker(m):
            async with sem:
                r = await scrape_model(context, m)
            status = "ok" if r["spec_count"] else f"FAIL ({r['scrape_error']})"
            print(f"    - {r['model'][:32]:<32} {r['spec_count']:>3} specs  "
                  f"{len(r['options'].get('colors', []))} colors  [{status}]", file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r["model"] or "")
    out = {"source": BASE, "logo": LOGO, "collection": COLLECTION,
           "scraped_at": datetime.now(timezone.utc).isoformat(),
           "model_count": len(results), "models": results}
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Himiway e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/himiway_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
