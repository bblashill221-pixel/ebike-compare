#!/usr/bin/env python3
"""
Fill in each bike's rear-rack max load from the brand's accessory catalog.

A bike's own spec sheet often omits the rear rack's load rating, but the rack is
sold as an accessory whose product page lists it (e.g. Aventon's rear rack ->
"Load capacity: 55lbs"). For every model lacking a rack-load spec, this locates
the matching rear-rack accessory -- by shared model/family name, or a single
brand-wide rear rack -- fetches its page, reads the load, and injects a
"Rear Rack Max Load" spec row so analyze._rack_load_lb picks it up.

Run after enrich_shipping_accessories (which populates available_accessories) and
before normalize. Network: one fetch per rear-rack accessory per brand (cached).

Usage:  python enrich_rack_load.py [--brand NAME]
"""
import argparse
import glob
import html
import json
import re
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
# Persistent cache of rack-page -> load lookups (rack ratings are static), keyed
# by accessory URL. Lives in data/curated/ so it survives daily re-scrapes: a run
# reuses cached loads (no re-fetch) and a transient fetch failure falls back to
# the cached value instead of dropping the spec (which would be a false "change").
_CACHE_PATH = DATA / "curated" / "rack_load.json"
try:
    _RACK_CACHE: dict = json.loads(_CACHE_PATH.read_text())
except (FileNotFoundError, ValueError):
    _RACK_CACHE = {}
_CACHE_DIRTY = False

_REAR_RACK = re.compile(r"rear\s*rack|\brack\b", re.I)
_NOT_RACK = re.compile(r"front|hitch|pannier|\bbag\b|basket|trailer|surf|phone|cup|\bmount\b", re.I)
_LOAD_RE = re.compile(
    r"(?:load\s*capac\w*|max(?:imum)?\s*(?:load|weight)|weight\s*(?:limit|capac\w*))"
    r"[^0-9]{0,12}(\d{2,3})\s*(lb|kg)", re.I)
_STOP = {"ebike", "ebikes", "electric", "bike", "bikes", "step", "thru", "through",
         "over", "rack", "rear", "front", "set", "the"}


def _load_from_page(url: str) -> int | None:
    global _CACHE_DIRTY
    if not url:
        return None
    if url in _RACK_CACHE:                 # static rating: reuse, never re-fetch
        return _RACK_CACHE[url]
    try:
        raw = urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20
        ).read().decode("utf-8", "ignore")
    except Exception:
        return _RACK_CACHE.get(url)        # transient failure -> last-known (may be None)
    txt = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", raw)).split())
    m = _LOAD_RE.search(txt)
    val = (round(int(m.group(1)) * 2.2046) if m.group(2).lower() == "kg"
           else int(m.group(1))) if m else None
    if val is not None:                    # only cache successful reads
        _RACK_CACHE[url] = val
        _CACHE_DIRTY = True
    return val


def _tokens(name: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if t not in _STOP}


def _name(model: dict) -> str:
    return model.get("model") or model.get("title") or ""   # brands differ on the key


def _has_rack_load(model: dict) -> bool:
    specs = (model.get("specs") or {}).get("all") or {}
    return any(re.search(r"rack.*(load|capac|weight)", k, re.I) for k in specs)


def enrich(d: dict, brand: str) -> int:
    accs = d.get("available_accessories") or []
    rear = [a for a in accs
            if _REAR_RACK.search(a.get("name", "")) and not _NOT_RACK.search(a.get("name", ""))]
    racks = [(a["name"], ld) for a in rear if (ld := _load_from_page(a.get("url", "")))]
    if not racks:
        return 0
    universal = racks[0][1] if len(racks) == 1 else None
    added = 0
    for m in d.get("models", []):
        if _has_rack_load(m):
            continue
        toks = _tokens(_name(m))
        load = next((rl for rn, rl in racks if _tokens(rn) & toks), universal)
        if load:
            m.setdefault("specs", {}).setdefault("all", {})["Rear Rack Max Load"] = f"{load} lbs"
            added += 1
    return added


def main():
    ap = argparse.ArgumentParser(description="Fill rear-rack max load from accessory catalogs.")
    ap.add_argument("--brand", default=None, help="only this brand (e.g. aventon)")
    args = ap.parse_args()
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        if args.brand and brand != args.brand:
            continue
        d = json.load(open(f))
        added = enrich(d, brand)
        if added:
            Path(f).write_text(json.dumps(d, indent=2, ensure_ascii=False))
            print(f"{brand:<12} rear-rack load added to {added} models")
    if _CACHE_DIRTY:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(_RACK_CACHE, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
