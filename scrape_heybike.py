#!/usr/bin/env python3
"""
Heybike e-bike spec scraper.

Heybike is a Shopify store. Models are discovered from the electric-bike
collection feed; each product page is rendered with Playwright to extract the
spec accordions. Colors are emitted as {name, hex, image}:

  * name  -- the Shopify "Color" variant option value,
  * image -- that color's variant photo (from the catalog feed),
  * hex   -- resolved from the swatch's `--swatch-background` keyword (Heybike
             uses image swatches and only exposes a colour keyword, so hex is
             best-effort: solid CSS colours resolve, fancy names stay null).

Output JSON mirrors the Aventon/Lectric scrapers.

Usage:
    python scrape_heybike.py                  # all models -> heybike_ebikes.json
    python scrape_heybike.py --limit 3        # quick test (first 3 models)
    python scrape_heybike.py -o out.json      # custom output path
    python scrape_heybike.py --concurrency 2  # parallel product pages
    python scrape_heybike.py --headed         # watch the browser
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

BASE = "https://www.heybike.com"
LOGO = "https://www.heybike.com/cdn/shop/files/heybike-logo_c0d69677-ad00-41d8-940c-f1aeac5cee34.svg?v=1745923766&width=500"
COLLECTION = "electric-bike"


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
            if o["name"].lower().startswith("color"):   # "Color" or "Colors"
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

# Expand all spec accordions, then read the spec rows. Heybike uses two
# templates: (A) <h6>label</h6><p>value</p>, and (B) <p><strong>Label:
# </strong>value<br>...</p>.
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    // Scan the whole document, not just the specs section: some models render
    // spec rows outside .specifications-section. The structural guards below
    // (h6 immediately followed by p; <strong>label:</strong> runs; length caps)
    // keep unrelated bold/heading text out.
    const sec = document;
    sec.querySelectorAll('details').forEach(d => { try { d.open = true; } catch (e) {} });
    const out = [];
    // Template A: h6 -> following p.
    for (const h of sec.querySelectorAll('h6')) {
        const p = h.nextElementSibling;
        if (p && p.tagName === 'P') {
            const label = norm(h.innerText), value = norm(p.innerText);
            if (label && value) out.push([label, value]);
        }
    }
    if (out.length) return out;
    // Template B: <strong>Label:</strong> value (text runs until the next
    // <strong>). Used by some models in .specification or .child-content blocks.
    const seen = new Set();
    for (const strong of sec.querySelectorAll('.specification strong, .child-content strong, strong')) {
        const label = norm(strong.textContent).replace(/:$/, '').trim();
        if (!label || label.length > 40 || seen.has(label)) continue;
        let value = '';
        let n = strong.nextSibling;
        while (n && !(n.nodeType === 1 && n.tagName === 'STRONG')) {
            if (!(n.nodeType === 1 && n.tagName === 'BR')) value += n.textContent || '';
            n = n.nextSibling;
        }
        value = norm(value);
        if (value) { seen.add(label); out.push([label, value]); }
    }
    return out;
}"""

# Range fallback: many Heybike spec tables omit a Range row and only state it
# in marketing copy. Sources, most structured first: the "introduce" highlight
# strip ('55 Miles' / 'Max Range' title+remark pairs), then feature cards
# ("60 Miles of Range") and description prose ("up to 60 miles"). Never review
# widgets, where riders quote their own mileage. Returns "Up to N miles" or null.
JS_RANGE_CLAIM = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const inReviews = el =>
        !!el.closest('[class*="review"], [id*="review"], [class*="jdgm"]');
    const milesOf = text => {
        const m = text.match(/\b(\d{2,3})\s*\+?\s*miles?\b/i);
        const mi = m && parseInt(m[1], 10);
        return (mi && mi >= 15 && mi <= 200) ? mi : null;
    };
    for (const el of document.querySelectorAll('.introduce-info')) {
        const text = norm(el.textContent);          // "55 Miles Max Range"
        if (/range/i.test(text)) {
            const mi = milesOf(text);
            if (mi) return `Up to ${mi} miles`;
        }
    }
    const PATS = [
        /up\s+to\s+(\d{2,3})\s*\+?\s*miles?\b/i,           // "up to 60 miles"
        /\b(\d{2,3})\s*\+?\s*miles?\s+(?:of\s+)?range\b/i,  // "90 Miles Range"
    ];
    for (const sel of ['.feature-heading', '.feature-desc', '[class*="description"]']) {
        for (const el of document.querySelectorAll(sel)) {
            if (inReviews(el)) continue;
            const text = norm(el.textContent);
            for (const rx of PATS) {
                const m = text.match(rx);
                const mi = m && parseInt(m[1], 10);
                if (mi && mi >= 15 && mi <= 200) return `Up to ${mi} miles`;
            }
        }
    }
    return null;
}"""

# Resolve each swatch's --swatch-background keyword to a hex (valid CSS colours
# only; image-swatch keywords like "pearl"/"sunset" resolve to null).
JS_SWATCH_HEX = r"""() => {
    const toHex = s => {
        const m = s && s.match(/\d+/g);
        return (m && m.length >= 3)
            ? '#' + m.slice(0,3).map(x => (+x).toString(16).padStart(2,'0')).join('') : null;
    };
    const probe = document.createElement('span');
    document.body.appendChild(probe);
    const resolve = kw => {
        if (!kw) return null;
        probe.style.color = '';
        probe.style.color = kw;
        if (!probe.style.color) return null;          // invalid keyword
        return toHex(getComputedStyle(probe).color);
    };
    const urlOf = v => {
        const m = v && v.match(/url\("?(.*?)"?\)/);
        return m ? (m[1].startsWith('//') ? 'https:' + m[1] : m[1]) : null;
    };
    const out = {};
    for (const el of document.querySelectorAll('.color-swatch')) {
        const title = el.getAttribute('title');
        if (!title) continue;
        out[title] = {
            hex: resolve(el.style.getPropertyValue('--swatch-background').trim()),
            swatch_image: urlOf(el.style.getPropertyValue('--swatch-background-image').trim())
                          || urlOf(getComputedStyle(el).backgroundImage),
        };
    }
    probe.remove();
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
                await page.wait_for_selector(".specifications-section, .specification",
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
            # No Range row in the spec table -> fall back to the marketing claim.
            if pairs and not any("range" in label.lower() for label, _ in pairs):
                claim = await page.evaluate(JS_RANGE_CLAIM)
                if claim:
                    pairs.append(["Range", claim])
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
    ap = argparse.ArgumentParser(description="Scrape Heybike e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/heybike_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
