#!/usr/bin/env python3
"""
Monarc (monarcbike.com) e-bike spec scraper (Shopify).

Monarc sells the "Marker" e-bike line as a handful of `product_type` "Bike"
products (one per frame/colour combo). Each product page is rendered with
Playwright to read the spec sheet, which Monarc renders as repeated
`.faq-pdp__spec-row` blocks (a detailed list plus a shorter `--compact`
summary); rows are read label:value and de-duplicated by label. Colours are
emitted as {name, hex, swatch_image, image}. Output mirrors the other scrapers.

Usage:
    python scrape_monarc.py [-o out.json] [--limit N] [--concurrency N] [--headed]
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


from scraper_common import fetch_json, clean_title, build_colors, make_classifier  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://monarcbike.com"
LOGO = "https://monarcbikes.com/cdn/shop/files/logo-lectric-brand.svg?v=1776703367"
COLLECTION = "marker-bikes"

TECHNICAL_KEYWORDS = (
    "motor", "battery", "cell", "charger", "charging", "range", "controller",
    "throttle", "display", "sensor", "pedal assist", "pas", "speed", "class",
    "watt", "voltage", "torque", "power", "app", "connectivity", "wireless",
    "gps", "ip", "certif", "riding mode", "waterproof",
)
PHYSICAL_KEYWORDS = (
    "frame", "fork", "suspension", "wheel", "tire", "tyre", "brake", "rotor",
    "derailleur", "shift", "chain", "cassette", "gear", "crank", "chainring",
    "pedal", "saddle", "seat", "handlebar", "stem", "grip", "headset",
    "kickstand", "rack", "fender", "light", "spoke", "hub", "rim", "weight",
    "payload", "load", "capacity", "height", "size", "color", "colour",
    "dimension", "axle", "sprocket", "cog", "tube", "reach", "stack",
    "wheelbase", "standover", "inseam",
)


classify = make_classifier(TECHNICAL_KEYWORDS, PHYSICAL_KEYWORDS)


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        if (p.get("product_type") or "").lower() != "bike":
            continue
        variants = p.get("variants", [])
        prices = [float(v["price"]) for v in variants if v.get("price")]
        images = [img.get("src") for img in p.get("images", []) if img.get("src")]
        fallback = images[0] if images else None
        options, color_values, color_idx = {}, [], None
        for i, o in enumerate(p.get("options", [])):
            if not o.get("name"):
                continue
            if "color" in o["name"].lower() or "colour" in o["name"].lower():
                color_values = o.get("values", [])
                color_idx = i + 1
            else:
                options[o["name"]] = o.get("values", [])
        options["colors"] = build_colors(color_values, color_idx, variants, fallback)
        models.append({
            "model": clean_title(p.get("title")),
            "handle": p.get("handle"),
            "url": f"{BASE}/products/{p['handle']}",
            "product_type": p.get("product_type"),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
        })
    return models


# Monarc renders specs as repeated rows: a detailed `.faq-pdp__specs` list and a
# shorter `.faq-pdp__specs--compact` summary. Read every row label:value and let
# the caller de-duplicate by label (the compact rows are a subset of the full).
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [], seen = new Set();
    for (const row of document.querySelectorAll('.faq-pdp__spec-row')) {
        const label = norm(row.querySelector('.faq-pdp__spec-name')?.textContent);
        const value = norm(row.querySelector('.faq-pdp__spec-value')?.textContent);
        if (!label || !value || label.length > 60) continue;
        if (seen.has(label)) continue;
        seen.add(label);
        out.push([label, value]);
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
                await page.wait_for_selector(".faq-pdp__spec-row", state="attached", timeout=20000)
            except Exception:
                pass
            pairs = []
            for _ in range(20):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

            physical, technical, all_specs = {}, {}, {}
            for label, value in pairs:
                key = " ".join(label.split())
                all_specs[key] = value
                (physical if classify(key) == "physical" else technical)[key] = value

            result["specs"] = {"physical": physical, "technical": technical, "all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result["specs"] = {"physical": {}, "technical": {}, "all": {}}
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


async def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE} ...", file=sys.stderr)
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
    ap = argparse.ArgumentParser(description="Scrape Monarc e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/monarc_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
