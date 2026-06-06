#!/usr/bin/env python3
"""
Shared helpers for the e-bike scrapers.

Centralizes the boilerplate every scraper repeated verbatim so a change here is
global to all of them: the bundled-Chromium library path, Shopify JSON fetching,
product-title cleaning, the physical/technical spec classifier, and Shopify
colour-swatch assembly.

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


def make_classifier(technical, physical, default: str = "physical"):
    """Build a label -> 'physical'/'technical' classifier bound to the given keyword
    tuples. Physical keywords are checked first (they win ties); `default` is the
    fallback when no keyword matches. Keyword tuples stay per-scraper (each site
    tunes them to its own spec labels); only the algorithm is shared."""
    def classify(label: str) -> str:
        low = label.lower()
        for kw in physical:
            if kw in low:
                return "physical"
        for kw in technical:
            if kw in low:
                return "technical"
        return default
    return classify


def build_colors(color_values, color_idx, variants, fallback_image):
    """Assemble {name, hex, swatch_image, image} colour entries from Shopify option
    values, using each colour variant's featured image when available."""
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
