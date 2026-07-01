#!/usr/bin/env python3
"""
Shared helpers for the e-bike scrapers.

Centralizes the boilerplate every scraper repeated verbatim so a change here is
global to all of them: the bundled-Chromium library path, Shopify JSON fetching,
product-title cleaning, and Shopify colour-swatch assembly.

IMPORTANT: importing this module also sets LD_LIBRARY_PATH for the bundled
Chromium, which Playwright reads at import time -- so each scraper imports
scraper_common BEFORE `from playwright... import ...`.
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from pathlib import Path

# --- bundled chromium deps: must be set before playwright is imported ----------
_DEPS = Path(__file__).parent / ".chromium-deps" / "root"
if _DEPS.exists():
    os.environ["LD_LIBRARY_PATH"] = os.pathsep.join([
        str(_DEPS / "usr/lib/x86_64-linux-gnu"),
        str(_DEPS / "lib/x86_64-linux-gnu"),
        os.environ.get("LD_LIBRARY_PATH", ""),
    ]).strip(os.pathsep)


def fetch_json(url: str) -> dict:
    """GET a URL and parse it as JSON (used for Shopify products.json etc.)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def clean_title(t: str) -> str:
    """Strip HTML tags/entities from a Shopify product title."""
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).replace("  ", " ").strip()


def build_colors(color_values, color_idx, variants, fallback_image):
    """Assemble {name, hex, swatch_image, image} colour entries from Shopify option
    values, using each colour variant's featured image when available. Products
    sold without a Color option still get one "Default" entry carrying the
    catalog photo — every model must surface at least one image."""
    if not color_values:
        if fallback_image:
            return [{"name": "Default", "hex": None, "swatch_image": None,
                     "image": fallback_image}]
        return []
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


def shopify_sold_out_options(products):
    """From a Shopify product (or the list of products that make up one model),
    return (sold_out_options, in_stock).

    `sold_out_options` maps each option axis (Color / Frame / Size / ...) to the
    values whose EVERY variant is unavailable -- i.e. the colorways/frames/sizes a
    buyer can no longer order (a value still available in some combo is omitted).
    `in_stock` is True when any variant is available, False when all are sold out,
    None when the feed carried no `available` flags. Mirrors normalize._availability
    but reads the raw Shopify variant `available` field directly at scrape time."""
    if isinstance(products, dict):
        products = [products]
    val_ok: dict = {}          # (axis, value) -> available somewhere?
    saw_flag = False
    for p in products or []:
        names = [o.get("name") for o in (p.get("options") or [])]
        for v in p.get("variants", []):
            avail = v.get("available")
            if avail is None:
                continue
            saw_flag = True
            for i, name in enumerate(names, start=1):
                val = v.get(f"option{i}")
                if not name or not val or val == "Default Title":
                    continue
                key = (name, str(val))
                val_ok[key] = val_ok.get(key, False) or bool(avail)
    if not saw_flag:
        return {}, None
    sold_out: dict = {}
    for (axis, val), ok in val_ok.items():
        if not ok:
            sold_out.setdefault(axis, []).append(val)
    for axis in sold_out:
        sold_out[axis] = sorted(dict.fromkeys(sold_out[axis]))
    return sold_out, any(val_ok.values())
