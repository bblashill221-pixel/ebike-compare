#!/usr/bin/env python3
"""
Resolve image-locked rider-height ranges via Claude vision.

Many bikes publish their per-size rider-height fit ONLY in a size-guide / dimensions
image (a bike outline with man/woman silhouettes + heights), which the text-only
scrapers and the text resolver (`resolve_missing_fields.py`) can't read. This stage
closes that last gap:

  1. for every model still missing a rider-height range (audit's
     `frame_size_rider_range` / `fit_height_min_in`), find the best size-guide
     image on its product page (filename/alt heuristics + a content-image scan);
  2. ask Claude (vision) for the per-size rider-height ranges as JSON;
  3. cache the result by model id in data/curated/image_heights.json, which
     normalize.py merges into the model (geometry rider_height_range + frame_sizes).

Cache-first like llm_parse_components: a cached model is never re-fetched, so the
pipeline never blocks on the network/LLM. Needs ANTHROPIC_API_KEY only to fill new
entries.

Usage:
    python resolve_image_heights.py --plan          # list candidates (no LLM)
    python resolve_image_heights.py --run [--limit N]   # extract + cache (needs key)
"""
from __future__ import annotations

import argparse
import html
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "current" / "active" / "ebikes_normalized.json"
CACHE_PATH = DATA / "curated" / "image_heights.json"
WORKLIST = DATA / "current" / "image_height_worklist.json"

# Filename/alt hints that a content image is a size/dimensions/fit guide.
_SIZE_IMG = re.compile(r"size|sizing|dimension|geometry|fit[\s_-]?guide|rider|height|"
                       r"\d{3,4}_\d{3,4}|measurement", re.I)
_UA = {"User-Agent": "Mozilla/5.0"}


def _get(url: str) -> str:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def _needs_height(m: dict) -> bool:
    miss = (m.get("data_audit") or {}).get("missing", [])
    return "fit_height_min_in" in miss or "frame_size_rider_range" in miss


def candidate_images(url: str) -> list[str]:
    """Content images on a product page most likely to be a size/dimensions guide,
    best-named first. Static fetch (most brands inline these in the description)."""
    page = _get(url)
    if not page:
        return []
    imgs = re.findall(r'(?:src|data-src)="(//[^"]+\.(?:jpg|jpeg|png|webp)[^"]*|https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', page, re.I)
    seen, named, other = set(), [], []
    for u in imgs:
        u = html.unescape(u)
        full = ("https:" + u) if u.startswith("//") else u
        base = full.split("?")[0]
        if base in seen or re.search(r"logo|icon|favicon|sprite|swatch|payment", base, re.I):
            continue
        seen.add(base)
        (named if _SIZE_IMG.search(base) else other).append(full)
    return named + other[:8]   # named candidates first, then a few generic content imgs


def cmd_plan():
    doc = json.load(open(ACTIVE))
    work = {}
    for m in doc.get("models", []):
        if not _needs_height(m) or not m.get("url"):
            continue
        cands = candidate_images(m["url"])
        if cands:
            work[m["id"]] = {"brand": m["brand"], "model": m["model"], "url": m["url"],
                             "candidates": cands[:6]}
    WORKLIST.write_text(json.dumps(work, indent=1, ensure_ascii=False))
    named = sum(1 for v in work.values() if _SIZE_IMG.search(v["candidates"][0]))
    print(f"[plan] {len(work)} models missing rider height have candidate images "
          f"({named} with a size/dimensions-named image first) -> {WORKLIST}")


_PROMPT = (
    "This is an e-bike product image. If it is a SIZE/DIMENSIONS guide showing rider "
    "height fit (often a bike outline with human silhouettes and heights), return the "
    "rider-height range(s). Reply ONLY JSON: "
    '{"frame_sizes":[{"size":<label or null>,"height_min":"5\'2\\"","height_max":"6\'5\\""}]} '
    'or {"frame_sizes":[]} if the image has no rider-height information.'
)


def _extract(client, url: str) -> dict | None:
    import base64
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=30).read()
    except Exception:
        return None
    media = "image/png" if url.lower().split("?")[0].endswith("png") else "image/jpeg"
    msg = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media,
                                         "data": base64.standard_b64encode(raw).decode()}},
            {"type": "text", "text": _PROMPT},
        ]}],
    )
    txt = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    mm = re.search(r"\{.*\}", txt, re.S)
    if not mm:
        return None
    try:
        out = json.loads(mm.group(0))
    except ValueError:
        return None
    return out if out.get("frame_sizes") else None


def cmd_run(limit: int):
    import anthropic
    client = anthropic.Anthropic()
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    doc = json.load(open(ACTIVE))
    todo = [m for m in doc.get("models", []) if _needs_height(m) and m.get("url") and m["id"] not in cache]
    if limit:
        todo = todo[:limit]
    filled = 0
    for m in todo:
        for img in candidate_images(m["url"])[:4]:
            res = _extract(client, img)
            if res:
                cache[m["id"]] = {**res, "_image": img,
                                  "_extracted_at": datetime.now(timezone.utc).isoformat()}
                filled += 1
                print(f"  {m['brand']:10} {m['model'][:34]:35} -> {res['frame_sizes']}")
                break
    CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(f"[run] extracted {filled}/{len(todo)} -> {CACHE_PATH}")


def main():
    ap = argparse.ArgumentParser(description="Resolve image-locked rider heights via Claude vision.")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if args.run:
        cmd_run(args.limit)
    else:
        cmd_plan()


if __name__ == "__main__":
    main()
