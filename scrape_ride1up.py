#!/usr/bin/env python3
"""
Ride1Up e-bike spec scraper.

Ride1Up runs on WooCommerce (not Shopify). Models are discovered from the
"bikes" category grid, then Playwright opens each product page to extract:

  * specifications (the "Components & Tech Specs" list),
  * available options (the WooCommerce variation attributes: frame type,
    drivetrain, color, ...),
  * colors as {name, hex, image} -- the hex is sampled from the swatch image's
    pixels (Ride1Up uses image swatches, not solid-color chips), and the image
    is the color's own variation photo.

Output JSON mirrors the Aventon/Lectric scrapers.

Usage:
    python scrape_ride1up.py                  # all models -> ride1up_ebikes.json
    python scrape_ride1up.py --limit 2        # quick test (first 2 models)
    python scrape_ride1up.py -o out.json      # custom output path
    python scrape_ride1up.py --concurrency 2  # parallel product pages
    python scrape_ride1up.py --headed         # watch the browser
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

# --- Make the locally-extracted Chromium system libs discoverable, if present. ---

import scraper_common  # noqa: E402,F401  (sets LD_LIBRARY_PATH for bundled chromium)
from bike_taxonomy import classify_product_types
from playwright.async_api import async_playwright  # noqa: E402
from warranty_js import JS_WARRANTY

BASE = "https://ride1up.com"
LOGO = "https://ride1up.com/wp-content/uploads/2021/01/ride1up.svg"
BIKES_CATEGORY = f"{BASE}/product-category/bikes/?per_page=50"


# ----------------------------- catalog discovery -----------------------------

def discover_models() -> list[dict]:
    """Parse the bikes-category product grid for the current model lineup."""
    req = urllib.request.Request(BIKES_CATEGORY, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", "ignore")
    # Restrict to the main product grid (ul.products.columns-*).
    m = re.search(r'<ul[^>]*class="[^"]*products[^"]*columns[^"]*"[^>]*>(.*?)</ul>',
                  html, re.S)
    region = m.group(1) if m else html
    urls = re.findall(r'href="(https://ride1up\.com/product/[a-z0-9-]+/)"', region)
    models = []
    seen = set()
    for u in urls:
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if slug in seen:
            continue
        seen.add(slug)
        models.append({"slug": slug, "url": u})
    return models


# ------------------------------ page extraction ------------------------------

# Variations + attribute option names from the WooCommerce variations form.
# Per-frame sizing: Ride1Up's chart tabs are frame variants (ST/XR), each with a
# rider-height range (detailed dims are in a diagram image, not text).
JS_GEOMETRY = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const tabs = [...document.querySelectorAll('.frame-size-tabs button')].map(b => norm(b.innerText));
    const secs = [...document.querySelectorAll('.frame-size-section')];
    const byFrame = {};
    secs.forEach((sec, i) => {
        const frame = tabs[i] || ('Variant ' + (i + 1));
        const t = norm(sec.innerText);
        let m = t.match(/Rider Height Range:.*?(\d+'\s*\d*"?\s*[-–]\s*\d+'\s*\d*")/i);
        if (!m) m = t.match(/Rider Height Range:\s*([^*]+?)(?:\s+\d+'\d*"?\/|\s*\*|$)/i);
        if (m) byFrame[frame] = norm(m[1]);
    });
    return Object.keys(byFrame).length ? {"Rider Height Range": byFrame} : {};
}"""

# Newer Ride1Up product layout (e.g. TrailRush): the per-size dimensions live in
# a text table `.bike-dimensions-table`, NOT the `.frame-size-section` blocks the
# extractor above reads. The header lists the size names (LARGE / MED), the
# `.big-col-holder` lists the row labels (Rider Height range, A-O dims, ...), and
# each `.small-col-holder` is one size's value column (in header order). We pull
# the whole table so frame sizes, rider-height ranges, and geometry are all
# captured as text -- the only thing in the diagram image is the letter callouts.
JS_DIM_TABLE = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const t = document.querySelector('.bike-dimensions-table');
    if (!t) return null;
    const sizes = [...t.querySelectorAll('.bike-dimensions-table-head .small-col')]
        .map(e => norm(e.innerText)).filter(Boolean);
    const labels = [...t.querySelectorAll('.big-col-holder .big-col-item')]
        .map(e => norm(e.innerText));
    const cols = [...t.querySelectorAll('.small-col-holder')].map(col =>
        [...col.querySelectorAll('.small-col-item')]
            .map(it => norm((it.querySelector('.shown-value') || it).innerText)));
    if (!sizes.length || !labels.length || !cols.length) return null;
    const out = {};
    sizes.forEach((sz, ci) => {
        const vals = cols[ci] || [];
        const row = {};
        labels.forEach((lab, ri) => {
            if (vals[ri] !== undefined && vals[ri] !== '') row[lab] = vals[ri];
        });
        out[sz] = row;
    });
    return out;
}"""

JS_VARIATIONS = r"""() => {
    const form = document.querySelector('form.variations_form');
    const out = {variations: [], attributes: {}};
    if (!form) return out;
    try { out.variations = JSON.parse(form.getAttribute('data-product_variations') || '[]'); }
    catch (e) { out.variations = []; }
    for (const sel of form.querySelectorAll('select[name^="attribute_"]')) {
        const attr = sel.getAttribute('name');
        const opts = {};
        for (const o of sel.querySelectorAll('option')) {
            if (o.value) opts[o.value] = o.textContent.trim();
        }
        out.attributes[attr] = opts;
    }
    return out;
}"""

# Canonical spec sheet: the "Components & Tech Specs" list (title -> subtitle),
# plus the headline highlight grid (<h3>UPPERCASE</h3> -> value).
JS_SPECS = r"""() => {
    const norm = s => (s || '').replace(/\s+/g, ' ').trim();
    const components = [], highlights = [];
    for (const row of document.querySelectorAll('.component-text')) {
        const title = norm(row.querySelector('.component-title')?.innerText);
        const sub = norm(row.querySelector('.component-subtitle')?.innerText);
        if (title && sub) components.push([title, sub]);
    }
    for (const h of document.querySelectorAll('h3')) {
        const head = norm(h.innerText);
        if (!head || head !== head.toUpperCase() || head.length > 22) continue;
        let v = norm(h.nextElementSibling?.innerText);
        if (!v) {
            const pt = norm(h.parentElement?.innerText);
            if (pt.startsWith(head)) v = norm(pt.slice(head.length));
        }
        if (v) highlights.push([head, v]);
    }
    // "At A Glance" feature tiles (Range / Motor / Speed ...): mixed-case
    // titles, so the uppercase-h3 loop above skips them on layouts that use
    // this section instead of highlight chips (e.g. Prodigy v2).
    const glance = [];
    for (const it of document.querySelectorAll('.bike-features-item')) {
        const t = norm(it.querySelector('.feature-title')?.innerText);
        const v = norm(it.querySelector('.feature-subtitle')?.innerText);
        if (t && v) glance.push([t, v]);
    }
    // Dimensions table: the only place the bike's own weight and payload
    // ("Bike Weight" / "Weight Capacity") are stated. Multi-frame models have
    // one value column per frame tab; join differing values with their
    // column headers.
    const dims = [];
    const tbl = document.querySelector('.bike-dimensions-table');
    if (tbl) {
        // Two nesting schemes exist: stacked sub-tables, each opened by its own
        // table-head (Prodigy: CHAIN/CVT weight table above the XR/ST geometry
        // table), and variant tabs sharing one head (Vorsa: tab-a/b/c). So:
        // segment on table-head boundaries in DOM order, then pair labels with
        // value columns per tab *within* a segment -- never across.
        const tabOf = el => ([...el.classList].find(c => /^tab-/.test(c)) || 'tab-a');
        const segs = [];
        let cur = null;
        for (const el of tbl.querySelectorAll(
                '.bike-dimensions-table-head, .big-col-holder, .small-col-holder')) {
            if (el.classList.contains('bike-dimensions-table-head')) {
                cur = {headEls: [...el.querySelectorAll('.small-col')], labelEls: [], holderEls: []};
                segs.push(cur);
            } else if (!cur) {
                continue;
            } else if (el.classList.contains('big-col-holder')) {
                cur.labelEls.push(...el.querySelectorAll('.big-col-item'));
            } else {
                cur.holderEls.push(el);
            }
        }
        for (const seg of segs) {
            for (const tab of [...new Set(seg.labelEls.map(tabOf))]) {
                const labels = seg.labelEls.filter(e => tabOf(e) === tab).map(e => norm(e.innerText));
                const heads = seg.headEls.filter(e => tabOf(e) === tab).map(e => norm(e.innerText));
                const cols = seg.holderEls.filter(e => tabOf(e) === tab).map(h =>
                    [...h.querySelectorAll('.small-col-item')].map(e =>
                        norm(e.querySelector('.shown-value')?.innerText || e.innerText)));
                labels.forEach((lab, i) => {
                    if (!/weight/i.test(lab)) return;
                    const vals = cols.map(c => c[i]).filter(Boolean);
                    if (!vals.length) return;
                    const v = new Set(vals).size === 1 ? vals[0]
                        : vals.map((x, j) => (heads[j] ? heads[j] + ': ' : '') + x).join(' / ');
                    dims.push([lab, v]);
                });
            }
        }
    }
    return {components, highlights, glance, dims};
}"""

# Color swatch -> hex. Ride1Up swatches are background images, so we sample the
# image's centre pixel on a canvas (same-origin, so the canvas isn't tainted).
# Solid-colour swatches fall back to the computed background-color.
JS_COLOR_HEX = r"""async () => {
    const toHex = (r, g, b) =>
        '#' + [r, g, b].map(x => Math.round(x).toString(16).padStart(2, '0')).join('');
    const rgb2hex = s => {
        const m = s && s.match(/\d+(\.\d+)?/g);
        return (m && m.length >= 3) ? toHex(+m[0], +m[1], +m[2]) : null;
    };
    const cont = document.querySelector('.tawcvs-swatches[data-attribute_name="attribute_pa_color"]');
    const out = {};
    if (!cont) return out;
    for (const sw of cont.querySelectorAll('.swatch')) {
        const slug = sw.getAttribute('data-value');
        if (!slug) continue;
        const cs = getComputedStyle(sw);
        const m = cs.backgroundImage && cs.backgroundImage.match(/url\("?(.*?)"?\)/);
        if (m) {
            // Image swatch: keep the image link and also sample a representative hex.
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
            } catch (e) { entry.hex = rgb2hex(cs.backgroundColor); }
            out[slug] = entry;
        } else {
            out[slug] = {hex: rgb2hex(cs.backgroundColor), swatch_image: null};
        }
    }
    return out;
}"""


def color_image_for(slug: str, variations: list[dict]) -> str | None:
    """First variation image whose color attribute matches `slug`."""
    for v in variations:
        if v.get("attributes", {}).get("attribute_pa_color") == slug:
            img = v.get("image") or {}
            src = img.get("full_src") or img.get("src")
            if src:
                return src
    return None


def build_options(attributes: dict, color_hex: dict, variations: list[dict],
                  fallback_image: str | None) -> dict:
    """Map WooCommerce attributes -> options dict. `pa_color` becomes the
    {name, hex, image} colors list; other attributes become value-name lists."""
    options: dict = {}
    colors = []
    for attr, values in attributes.items():
        key = attr.replace("attribute_pa_", "").replace("attribute_", "")
        if key == "color":
            for slug, name in values.items():
                entry = color_hex.get(slug) or {}
                hexv = entry.get("hex")
                colors.append({
                    "name": name,
                    "hex": hexv,
                    # swatch_image is a fallback only: drop it when a hex is known.
                    "swatch_image": None if hexv else entry.get("swatch_image"),
                    "image": color_image_for(slug, variations) or fallback_image,
                })
        else:
            options[key] = list(values.values())
    options["colors"] = colors
    return options


# Map a frame-size abbreviation/word to a canonical name. Full words (LARGE) fall
# through to title-case; abbreviations (MED, LG, XL) are expanded explicitly.
_SIZE_NAMES = {
    "XXS": "XX-Small", "XS": "X-Small", "S": "Small", "SM": "Small", "SML": "Small",
    "M": "Medium", "MD": "Medium", "MED": "Medium", "L": "Large", "LG": "Large",
    "LRG": "Large", "XL": "X-Large", "XXL": "XX-Large", "XXXL": "XXX-Large",
}
_RH_RE = re.compile(r"(\d+'\s*\d+\"?)\s*[-–—]\s*(\d+'\s*\d+\"?)")


def _norm_size(s: str) -> str:
    s = (s or "").strip()
    key = re.sub(r"[^A-Za-z]", "", s).upper()
    if key in _SIZE_NAMES:
        return _SIZE_NAMES[key]
    return s.title() if s else s


def _to_in(h: str | None):
    m = re.match(r"\s*(\d+)'\s*(\d+)", h or "")
    return int(m.group(1)) * 12 + int(m.group(2)) if m else None


def _parse_height_range(v: str):
    """('5'5"', '5'10"') from a rider-height-range cell, or (None, None)."""
    v = (v or "").replace("”", '"').replace("’", "'")
    m = _RH_RE.search(v)
    if not m:
        return (None, None)
    clean = lambda x: (x.replace(" ", "") + ('' if x.strip().endswith('"') else '"'))
    return (clean(m.group(1)), clean(m.group(2)))


def _frame_sizes_from_table(table) -> list | None:
    """Build [{size, height_min, height_max}, ...] from the dim-table dict,
    smallest frame first. Returns None when no per-size rider height is present."""
    if not isinstance(table, dict) or not table:
        return None
    out = []
    for size, rows in table.items():
        rh_key = next((k for k in rows if "rider" in k.lower() and "height" in k.lower()), None)
        lo, hi = _parse_height_range(rows.get(rh_key, "")) if rh_key else (None, None)
        out.append({"size": _norm_size(size), "height_min": lo, "height_max": hi})
    if not any(s["height_min"] for s in out):
        return None
    out.sort(key=lambda s: _to_in(s["height_min"]) if s["height_min"] else 999)
    return out


def _merge_dim_geometry(geometry: dict, table: dict) -> dict:
    """Fold the per-size dim table into the geometry dict as readable rows
    ("A - Maximum Seat Height" -> "Large: 31in | Medium: 29in")."""
    geometry = dict(geometry or {})
    labels: list[str] = []
    for rows in table.values():
        for k in rows:
            if k not in labels:
                labels.append(k)
    for lab in labels:
        parts = [f"{_norm_size(sz)}: {rows[lab]}" for sz, rows in table.items() if lab in rows]
        if parts:
            geometry.setdefault(lab, " | ".join(parts))
    return geometry


def _rider_height_envelope(frame_sizes: list) -> str | None:
    mins = [v for s in frame_sizes if (v := _to_in(s.get("height_min")))]
    maxs = [v for s in frame_sizes if (v := _to_in(s.get("height_max")))]
    if not (mins and maxs):
        return None
    fmt = lambda i: f"{i // 12}'{i % 12}\""
    return f"{fmt(min(mins))} - {fmt(max(maxs))}"


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
            await page.wait_for_timeout(1200)
            for _ in range(12):
                await page.mouse.wheel(0, 2500)
                await page.wait_for_timeout(250)
            await page.wait_for_selector(".component-text", state="attached", timeout=15000)

            name = (await page.evaluate(
                "() => (document.querySelector('h1.product_title, h1')?.innerText || '').trim()"
            )) or model["slug"]
            var = await page.evaluate(JS_VARIATIONS)
            raw = await page.evaluate(JS_SPECS)
            geometry = await page.evaluate(JS_GEOMETRY)
            dim_table = await page.evaluate(JS_DIM_TABLE)
            color_hex = await page.evaluate(JS_COLOR_HEX)
            fallback_image = await page.evaluate(
                "() => document.querySelector('meta[property=\"og:image\"]')?.content "
                "|| document.querySelector('.woocommerce-product-gallery img')?.src || null"
            )
            result["warranty"] = await page.evaluate(JS_WARRANTY)
            await page.close()

            variations = var.get("variations") or []
            all_specs = {}
            for label, value in raw["components"]:
                key = " ".join(label.split())
                all_specs[key] = value
            # Add headline highlights, at-a-glance tiles, and dimension-table
            # rows. The component list stays authoritative for duplicate keys --
            # except when the duplicate strictly contains the existing text,
            # i.e. it is the same fact with more detail (Revv1 DRT: component
            # "Motor: 52V Bafang RM G0F4" vs glance "Powerful 52V Bafang RM
            # G0F4 ... with 100nm torque") -- then upgrade to the richer row.
            for label, value in (raw["highlights"]
                                 + raw.get("glance", [])
                                 + raw.get("dims", [])):
                key = " ".join(label.split())
                existing = next((k for k in all_specs if k.lower() == key.lower()), None)
                if existing is None:
                    all_specs[key] = value
                elif (len(str(value)) > len(str(all_specs[existing]))
                      and str(all_specs[existing]).lower() in str(value).lower()):
                    all_specs[existing] = value

            if not all_specs:
                raise RuntimeError("no specs extracted")

            prices = [float(v["display_price"]) for v in variations
                      if v.get("display_price") is not None]
            attrs = var.get("attributes", {})
            result["model"] = name
            result["product_types"] = classify_product_types(name, "", model["url"])
            result["price_range"] = {
                "min": min(prices) if prices else None,
                "max": max(prices) if prices else None,
                "currency": "USD",
            }
            # Every configuration (variant) with its own price, not just the range.
            result["configurations"] = [
                {
                    "options": {a.replace("attribute_pa_", "").replace("attribute_", ""):
                                attrs.get(a, {}).get(slug, slug)
                                for a, slug in v.get("attributes", {}).items()},
                    "price": float(v["display_price"]) if v.get("display_price") is not None else None,
                    "sku": v.get("sku"),
                    # keep each variation's own photo so frame siblings get the
                    # right per-frame image (the colors list collapses to one
                    # photo per color; the frame split + _resolve_colors restore
                    # the correct one from these per-config images)
                    "image": (v.get("image") or {}).get("full_src") or (v.get("image") or {}).get("src"),
                }
                for v in variations
            ]
            result["options"] = build_options(var.get("attributes", {}), color_hex,
                                               variations, fallback_image)
            # Newer dim-table layout: capture frame sizes + per-size geometry as
            # text (older `.frame-size-section` models leave dim_table null).
            frame_sizes = _frame_sizes_from_table(dim_table)
            if frame_sizes:
                result["frame_sizes"] = frame_sizes
                geometry = _merge_dim_geometry(geometry, dim_table)
                env = _rider_height_envelope(frame_sizes)
                if env:
                    rh = next((k for k in all_specs if "rider" in k.lower()
                               and "height" in k.lower()), "Rider Height")
                    all_specs[rh] = env
            result["geometry"] = geometry
            result["specs"] = {"all": all_specs}
            result["spec_count"] = len(all_specs)
            result["scrape_error"] = None
            return result
        except Exception as e:  # noqa: BLE001
            await page.close()
            if attempt == retries:
                result.setdefault("model", model["slug"])
                result["price_range"] = {"min": None, "max": None, "currency": "USD"}
                result["options"] = {"colors": []}
                result["specs"] = {"all": {}}
                result["configurations"] = []
                result["spec_count"] = 0
                result["warranty"] = None
                result["scrape_error"] = f"{type(e).__name__}: {e}"
                return result
            await asyncio.sleep(2.0 * attempt)
    return result


# ----------------------------------- main ------------------------------------

async def run(args) -> int:
    print(f"[*] Discovering models from {BASE} bikes category ...", file=sys.stderr)
    models = discover_models()
    if args.limit:
        models = models[: args.limit]
    print(f"[*] Found {len(models)} bike model(s).", file=sys.stderr)

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
            print(f"    - {r.get('model', m['slug'])[:30]:<30} {r['spec_count']:>3} specs  "
                  f"{ncol} colors  [{status}]", file=sys.stderr)
            results.append(r)

        await asyncio.gather(*(worker(m) for m in models))
        await context.close()
        await browser.close()

    results.sort(key=lambda r: r.get("model") or r["slug"])
    out = {
        "source": BASE, "logo": LOGO,
        "category": "bikes",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "model_count": len(results),
        "models": results,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ok = sum(1 for r in results if r["spec_count"])
    print(f"[*] Wrote {args.output} ({ok}/{len(results)} models with specs).", file=sys.stderr)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Scrape Ride1Up e-bike specifications.")
    ap.add_argument("-o", "--output", default="data/current/ride1up_ebikes.json")
    ap.add_argument("--limit", type=int, default=0, help="Only scrape first N models.")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
