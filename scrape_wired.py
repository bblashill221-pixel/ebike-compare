#!/usr/bin/env python3
"""
WIRED Ebikes (wiredebikes.com) spec scraper (Shopify + Playwright).

The model list, colors and price come from the `wired-ebikes` collection feed.
WIRED builds product pages with GemPages: the user-facing specs are a RENDERED
stat grid (PEAK POWER / TOP SPEED / TORQUE / RANGE) plus a "Total weight of
bike …" callout — not the product's body_html, whose hidden "Specifications"
block is often stale (e.g. the Cruiser page shows 3200W / 90 mi / 153Nm / 35+ mph
and 115 lb, while its feed body_html says 3000W / 100 mi). So each page is
rendered and the displayed stats are read; body_html only fills descriptive specs
the grid lacks (battery, brakes, suspension, frame, display). Shipping is read
from the storefront (WIRED charges a flat fee — not free).

Usage:
    python scrape_wired.py [-o out.json] [--limit N] [--concurrency N] [--headed]
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from scraper_common import fetch_json, clean_title, build_colors  # noqa: E402  (also sets LD_LIBRARY_PATH)
from playwright.async_api import async_playwright  # noqa: E402

from bike_taxonomy import classify_product_types

BASE = "https://wiredebikes.com"
LOGO = "https://wiredebikes.com/cdn/shop/files/Wired_1200_600.png?v=1739722992"
COLLECTION = "wired-ebikes"


def detect_shipping() -> dict:
    """Infer shipping from the storefront -- free is only claimed when the site says
    so. WIRED advertises a flat fee ("Flat rate $275 shipping"), so it is NOT free."""
    try:
        req = urllib.request.Request(BASE + "/", headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    except Exception:
        return {"cost": None, "free": None}
    m = (re.search(r"flat[\s-]?rate[^$]{0,15}\$\s*(\d{2,4})\s*shipping", page, re.I)
         or re.search(r"\$\s*(\d{2,4})\s*flat[\s-]?rate\s*shipping", page, re.I))
    if m:
        cost = int(m.group(1))
        return {"cost": cost, "free": cost == 0}
    if re.search(r"free\s+shipping", page, re.I):
        return {"cost": 0, "free": True}
    return {"cost": None, "free": None}


def _li_pairs(block: str) -> dict:
    """`<li>Label: value</li>` items in `block` -> {label: value}."""
    out: dict[str, str] = {}
    for li in re.findall(r"<li[^>]*>(.*?)</li>", block, re.I | re.S):
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", li)).split())
        m = re.match(r"([A-Za-z][\w /&'+-]{1,28}?)\s*[:：]\s*(.+)", text)
        if not m:
            continue
        label, value = " ".join(m.group(1).split()), m.group(2).strip()
        if value and len(value) <= 200 and label.lower() not in out:
            out[label] = value
    return out


def parse_body_specs(body_html: str) -> dict:
    """Descriptive specs from the feed's "Specifications" list (battery, brakes, …)."""
    body_html = body_html or ""
    m = re.search(r"specification[s]?\s*</h\d>\s*(<ul[^>]*>.*?</ul>)", body_html, re.I | re.S)
    return _li_pairs(m.group(1)) if m else _li_pairs(body_html)


# Rendered hero stat grid: a big value with a small label. Read the label/value
# pairs; _STAT_LABEL maps each to the spec field the pipeline expects.
JS_STATS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const LAB = /^(peak power|top speed|max speed|torque|range|motor|battery|voltage)\b/i;
    const out = [];
    for (const lab of document.querySelectorAll('p,span,div,h4,h5')) {
        const L = norm(lab.textContent);
        if (!LAB.test(L) || L.length > 24) continue;
        let val = '';
        const par = lab.parentElement;
        const h = par && par.querySelector('h1,h2,h3,h4,[class*=gp-text-instant]');
        if (h) val = norm(h.textContent);
        if ((!val || val === L) && lab.previousElementSibling) val = norm(lab.previousElementSibling.textContent);
        if (val && val !== L && val.length < 40 && /\d/.test(val)) out.push([L, val]);
    }
    return out;
}"""

_STAT_LABEL = {
    "peak power": "Motor",   # "3200W" -> peak motor power
    "top speed": "Top Speed", "max speed": "Top Speed",
    "torque": "Torque", "range": "Range",
    "motor": "Motor", "battery": "Battery", "voltage": "Voltage",
}


def discover_models() -> list[dict]:
    data = fetch_json(f"{BASE}/collections/{COLLECTION}/products.json?limit=250")
    shipping = detect_shipping()
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
            # WIRED's whole line is moto/moped-style; titles carry no moto keyword,
            # so add one to the classifier signal to land them as eMoto.
            "product_types": classify_product_types(
                p.get("title") or "", p.get("product_type") or "",
                " ".join(p.get("tags") or []) + " moped-style"),
            "price_from": min(prices) if prices else None,
            "currency": "USD",
            "options": options,
            "shipping": shipping,       # found on the site, not assumed free
            "body_html": p.get("body_html") or "",
        })
    return models


def _stats_to_specs(stats: list, body_text: str, body_html: str) -> dict:
    """Merge the rendered hero stats (authoritative — what the page shows) + the
    weight callout, then fill remaining descriptive specs from the feed body_html."""
    specs: dict[str, str] = {}
    for label, value in stats:
        key = _STAT_LABEL.get(re.sub(r"\s*\(.*?\)", "", label).strip().lower())
        if not key or key in specs:
            continue
        if key == "Motor" and re.search(r"\d\s*w", value, re.I) and "peak" not in value.lower():
            value = f"{value} peak"
        specs[key] = value
    mw = (re.search(r"total weight[^=:\n]*both batteries\s*[=:]\s*([\d.]+)\s*lb", body_text, re.I)
          or re.search(r"\bweight[^=:\n]{0,30}[=:]\s*([\d.]+)\s*lb", body_text, re.I))
    if mw:
        specs.setdefault("Weight", f"{mw.group(1)} lbs")
    for label, value in parse_body_specs(body_html).items():
        specs.setdefault(label, value)
    return specs


async def scrape_model(context, model: dict, retries: int = 3) -> dict:
    result = dict(model)
    body_html = result.pop("body_html", "")
    for attempt in range(1, retries + 1):
        page = await context.new_page()
        try:
            await page.goto(model["url"], wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            for _ in range(22):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(150)
            stats = await page.evaluate(JS_STATS)
            body_text = await page.evaluate("() => document.body.innerText")
            await page.close()

            specs = _stats_to_specs(stats, body_text, body_html)
            if not specs:
                raise RuntimeError("no specs extracted")
            result["specs"] = {"all": specs}
            result["spec_count"] = len(specs)
            result["warranty"] = None
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                # last-ditch: body_html only, so the model still lands
                specs = parse_body_specs(body_html)
                result["specs"] = {"all": specs}
                result["spec_count"] = len(specs)
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


async def run(args) -> int:
    print(f"[*] Discovering e-bike models from {BASE}/collections/{COLLECTION} ...", file=sys.stderr)
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
    ap = argparse.ArgumentParser(description="Scrape WIRED e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/wired_ebikes.json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
