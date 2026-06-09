#!/usr/bin/env python3
"""
CEMOTO (cemotoride.com) e-bike spec scraper (Shopify).

Models are discovered from the all-electric-bikes collection feed (which already
excludes the brand's scooters / dirt-bike parts / accessories); each product page
is rendered with Playwright. CEMOTO builds its spec sheet as a `.yg-table` where
rows alternate: a `tr.yg-table-heading` of labels followed by a value row, paired
column-wise (the table is two spec columns wide). Those pairs are read here, plus
any plain tables as a fallback, and de-duplicated by label.
Colors are emitted as {name, hex, swatch_image, image}; CEMOTO names its color
option "颜色" (Chinese for "color"). Output mirrors the other scrapers
(specs.all flat label->value map).

Usage:
    python scrape_cemoto.py [-o out.json] [--limit N] [--concurrency N] [--headed]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (import also sets LD_LIBRARY_PATH for bundled chromium)
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

from bike_taxonomy import classify_product_types

BASE = "https://cemotoride.com"
LOGO = "https://cemotoride.com/cdn/shop/files/C.svg?v=1761903094&width=256"
COLLECTION = "all-electric-bikes"

# CEMOTO labels its color option in Chinese ("颜色"); accept the usual spellings
# too. "Title" is Shopify's placeholder option for single-variant products.
_COLOR_NAMES = {"color", "colour", "颜色"}


def _is_color_option(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in _COLOR_NAMES or "color" in n or "colour" in n or "颜色" in name


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
            name = o.get("name")
            if not name or name.strip().lower() == "title":
                continue
            if _is_color_option(name):
                color_values = o.get("values", [])
                color_idx = i + 1
            else:
                options[name] = o.get("values", [])
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


# Read the .yg-table spec grid: each tr.yg-table-heading holds the labels and the
# next row holds the values, paired by column. Fall back to any plain table.
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const out = [], seen = new Set();
    const push = (label, value) => {
        label = norm(label).replace(/[:∶]\s*$/, '').trim();
        value = norm(value);
        if (!label || !value || label.length > 45 || value.length > 240) return;
        if (label.toLowerCase() === value.toLowerCase()) return;
        const k = label.toLowerCase();
        if (seen.has(k)) return;
        seen.add(k);
        out.push([label, value]);
    };
    // 1. CEMOTO yg-table: heading row of labels + following value row
    for (const table of document.querySelectorAll('.yg-specification-wrapper table, table.yg-table')) {
        const rows = [...table.querySelectorAll('tr')];
        for (let i = 0; i + 1 < rows.length; i++) {
            if (!/yg-table-heading/.test(rows[i].className)) continue;
            if (/yg-table-heading/.test(rows[i + 1].className)) continue;
            const labels = [...rows[i].querySelectorAll('td,th')].map(c => norm(c.textContent));
            const vals = [...rows[i + 1].querySelectorAll('td,th')].map(c => norm(c.textContent));
            for (let j = 0; j < labels.length; j++) push(labels[j], vals[j] || '');
        }
    }
    // 2. fallback: any plain two-column table
    if (!out.length) {
        for (const r of document.querySelectorAll('table tr')) {
            const c = [...r.querySelectorAll('th,td')].map(x => norm(x.textContent));
            if (c.length >= 2 && c[0]) push(c[0], c.slice(1).join(' '));
        }
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
            for _ in range(20):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(200)
            pairs = []
            for _ in range(10):
                pairs = await page.evaluate(JS_SPECS)
                if pairs:
                    break
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(800)
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
    ap = argparse.ArgumentParser(description="Scrape CEMOTO e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/cemoto_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
