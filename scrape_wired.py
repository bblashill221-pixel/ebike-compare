#!/usr/bin/env python3
"""
WIRED Ebikes (wiredebikes.com) spec scraper (Shopify + Playwright).

The model list, colors and price come from the `wired-ebikes` collection feed.
WIRED builds product pages with GemPages. The full per-model spec sheet is a
rendered "DETAILED SPECS" section (categories -> spec label -> value: motor,
battery V/Ah, drivetrain, frame, fork, tires, display, range, top speed, …) plus
a "Total weight of bike …" callout. That section is authoritative; the product's
body_html "Specifications" block is stale (e.g. the Cruiser page lists a 60V
1500W motor peaking at 3200W, while body_html says 3000W). So each page is
rendered and the DETAILED SPECS read; body_html only fills anything still missing
(brakes, certifications). Shipping is read from the storefront (WIRED charges a
flat fee — not free).

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

from scraper_common import fetch_json, clean_title, build_colors, shopify_sold_out_options  # noqa: E402  (also sets LD_LIBRARY_PATH)
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


# Each product page has a "DETAILED SPECS" section: category headers, then a spec
# label (uppercase) followed by its value sentence(s). Comprehensive and per-model
# accurate (motor, battery V/Ah, drivetrain, frame, fork, tires, display, range),
# unlike the stale body_html. Parsed from the rendered page text.
_SPEC_CATEGORIES = {"MOTOR & PERFORMANCE", "BATTERY & ELECTRONICS", "FRAME & COMPONENTS",
                    "SAFETY & EXTRAS", "WARRANTY & SUPPORT", "GEOMETRY", "DETAILED SPECS"}
_SPEC_LABELS = {"MOTOR", "TOP SPEED", "RIDE MODES", "BATTERIES", "BATTERY", "CONTROLLER",
                "DISPLAY", "PEDAL ASSIST", "THROTTLE", "RANGE", "DRIVETRAIN", "FRAME",
                "FORK", "SHOCK", "TIRES", "TIRE", "BRAKES", "BRAKE", "SUSPENSION",
                "WHEELS", "WHEEL", "WARRANTY", "WEIGHT", "SENSOR", "CHARGER", "LIGHTS",
                "LIGHTING", "RACK", "FENDERS", "SADDLE", "STEM", "HANDLEBARS", "HORN",
                "KICKSTAND", "GEARING"}
_SPEC_END = ("HELP VIDEOS", "TERMS OF SERVICE", "EBIKE LAWS", "FREQUENTLY ASKED",
             "REVIEWS", "YOU MAY ALSO LIKE", "NEWSLETTER", "RETURNS")
_LABEL_FIX = {"BATTERIES": "Battery", "TIRE": "Tires", "BRAKE": "Brakes", "WHEEL": "Wheels"}


def parse_detailed_specs(body_text: str) -> dict:
    """Read the DETAILED SPECS list from the rendered page text into {label: value}."""
    lines = [l.strip() for l in body_text.split("\n") if l.strip()]
    try:
        start = next(i for i, l in enumerate(lines) if l.upper() == "DETAILED SPECS")
    except StopIteration:
        return {}
    out: dict[str, str] = {}
    cur, buf = None, []

    def flush():
        if cur and buf:
            out.setdefault(cur, " ".join(buf)[:200].strip())

    for l in lines[start + 1:]:
        u = l.upper()
        if any(u.startswith(e) for e in _SPEC_END):
            break
        if u in _SPEC_CATEGORIES:
            flush(); cur, buf = None, []
        elif u in _SPEC_LABELS and len(l) < 24:
            flush(); cur, buf = _LABEL_FIX.get(u, l.title()), []
        elif cur:
            buf.append(l)
    flush()
    return out


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
        so, ins = shopify_sold_out_options(p)
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
            "sold_out_options": so,
            "in_stock": ins,
            "shipping": shipping,       # found on the site, not assumed free
            "body_html": p.get("body_html") or "",
        })
    return models


def _merge_specs(body_text: str, body_html: str) -> dict:
    """DETAILED SPECS section (primary, comprehensive) + the weight callout, then
    fill anything still missing (brakes, certs) from the feed body_html."""
    specs = parse_detailed_specs(body_text)
    mw = (re.search(r"total weight[^=:\n]*both batteries\s*[=:]\s*([\d.]+)\s*lb", body_text, re.I)
          or re.search(r"\bweight[^=:\n]{0,30}[=:]\s*([\d.]+)\s*lb", body_text, re.I))
    if mw:
        specs.setdefault("Weight", f"{mw.group(1)} lbs")
    for label, value in parse_body_specs(body_html).items():
        specs.setdefault(label, value)
    # Brakes are quoted in a feature callout, not the DETAILED SPECS list, on the
    # high-power models -- grab the brake phrase if nothing else supplied one.
    if "Brakes" not in specs:
        mb = re.search(r"((?:dual\s+)?\d[\s-]?piston[\w\s-]{0,30}?brakes?"
                       r"|[\w-]{0,20}\s*hydraulic\s+(?:disc\s+)?brakes?)", body_text, re.I)
        if mb:
            specs["Brakes"] = " ".join(mb.group(1).split())[:80]
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
            body_text = await page.evaluate("() => document.body.innerText")
            await page.close()

            specs = _merge_specs(body_text, body_html)
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
