#!/usr/bin/env python3
"""
Velowave (velowave.com) e-bike spec scraper (Shopify).

Models are discovered from the all-ebikes collection feed (product_type
"Electric_Bicycles"); each product page is rendered with Playwright. Velowave
renders specs in three places, all read here and de-duplicated by label:
  * a detailed list of <li><b>Label:</b><span>value</span></li> rows,
  * a "key specs" block of <div><div>LABEL</div><div>value</div></div> tiles,
  * a geometry <table>.
Colors are emitted as {name, hex, swatch_image, image}. Output mirrors the
other scrapers.

Usage:
    python scrape_velowave.py [-o out.json] [--limit N] [--concurrency N] [--headed]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

from bike_taxonomy import classify_product_types

BASE = "https://velowave.com"
LOGO = "https://cdn.shopify.com/s/files/1/0554/8294/1627/files/15.svg?v=1734405074"
COLLECTION = "all-ebikes"
EBIKE_TYPE = "Electric_Bicycles"


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    models = []
    for p in data.get("products", []):
        if EBIKE_TYPE and (p.get("product_type") or "") != EBIKE_TYPE:
            continue
        variants = p.get("variants", [])
        prices = [float(v["price"]) for v in variants if v.get("price")]
        images = [img.get("src") for img in p.get("images", []) if img.get("src")]
        fallback = images[0] if images else None
        options, color_values, color_idx = {}, [], None
        for i, o in enumerate(p.get("options", [])):
            if not o.get("name"):
                continue
            if o["name"].lower().startswith(("color", "colour")):
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


# Read all three spec renderings, de-duplicating by label (first match wins, so
# the detailed <li> list takes precedence over the shorter key-spec tiles).
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [], seen = new Set();
    const push = (label, value) => {
        label = norm(label).replace(/:$/, '').trim();
        value = norm(value);
        if (!label || !value || label.length > 50) return;
        const k = label.toLowerCase();
        if (seen.has(k)) return;
        seen.add(k);
        out.push([label, value]);
    };
    // 1. detailed spec list: <li><b>Label:</b><span>value</span>
    for (const li of document.querySelectorAll('li')) {
        const b = li.querySelector('b, strong');
        if (!b) continue;
        const lab = norm(b.textContent);
        if (!/:\s*$/.test(lab)) continue;
        const full = norm(li.textContent);
        push(lab, full.slice(lab.length));
    }
    // 2. key-spec tiles: <div><div class="...uppercase">LABEL</div><div>value</div></div>
    for (const lab of document.querySelectorAll('div[class*="uppercase"]')) {
        const val = lab.nextElementSibling;
        if (val && !lab.children.length) push(lab.textContent, val.textContent);
    }
    // 3. geometry table
    for (const r of document.querySelectorAll('table tr')) {
        const c = [...r.querySelectorAll('th,td')].map(x => norm(x.textContent));
        if (c.length >= 2 && c[0] && c[1]) push(c[0], c.slice(1).join(' '));
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
            # Reveal the spec sheet (behind a "Specifications" tab / "Show More").
            for txt in ("Specifications", "Show More"):
                try:
                    await page.get_by_text(txt, exact=True).first.click(timeout=2000)
                    await page.wait_for_timeout(700)
                except Exception:
                    pass
            pairs = []
            for _ in range(12):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1000)
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            if not pairs:
                raise RuntimeError("no specs extracted")

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
    ap = argparse.ArgumentParser(description="Scrape Velowave e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/velowave_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
