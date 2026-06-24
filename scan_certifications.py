#!/usr/bin/env python3
"""Scan product pages of bikes NOT already flagged UL/EN-certified for a safety
certification stated in page PROSE (not just the spec table): UL 2849/2271/2580
or the equivalent EN 15194 (e.g. Tern). A hit requires the standard number AND a
nearby positive certification word, so "competitor lacks UL 2849"-style copy and
bare standard mentions don't false-positive.

Matches are written into data/curated/html_extracted.json as ul_listed=true (with
the snippet + url as provenance), which analyze.py applies when the spec sheet
didn't already establish certification.

Usage: python scan_certifications.py [--brand NAME] [--limit N]
"""
import argparse, json, re, html, urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(__file__).parent / "data"
ACTIVE = DATA / "current" / "active" / "ebike.json"
CURATED = DATA / "curated" / "html_extracted.json"
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"}
_STD = re.compile(r"\bUL[\s-]?(?:2849|2271|2580)\b|\bEN[\s-]?15194\b", re.I)
_POS = re.compile(r"certif|complian|compliant|tested|listed|approved|meets|rated|conform", re.I)
_NEG = re.compile(r"\b(not|without|lacks?|lacking|don'?t|doesn'?t|no)\b", re.I)


def fetch(url: str) -> str:
    try:
        h = urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=25).read().decode("utf-8", "ignore")
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())
    except Exception:
        return ""


def cert_in(text: str):
    """(standard, snippet) if a positively-stated UL/EN cert is on the page, else None."""
    for m in _STD.finditer(text):
        s, e = max(0, m.start() - 70), min(len(text), m.end() + 70)
        ctx = text[s:e]
        if _POS.search(ctx) and not _NEG.search(text[max(0, m.start() - 20):m.start()]):
            return m.group(0).upper(), ctx.strip()
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand"); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    doc = json.load(open(ACTIVE))
    todo = [m for m in doc["models"]
            if not (m.get("analysis", {}).get("specs_typed", {}) or {}).get("ul_listed")
            and m.get("url") and (not a.brand or m["brand"] == a.brand)]
    if a.limit:
        todo = todo[:a.limit]
    cur = json.loads(CURATED.read_text()) if CURATED.exists() else {}
    found = 0
    for i, m in enumerate(todo):
        hit = cert_in(fetch(m["url"]))
        tag = "--"
        if hit:
            std, snip = hit
            cur.setdefault(m["id"], {})["ul_listed"] = {
                "value": True, "snippet": snip, "source": m["url"],
                "standard": std, "resolved_at": datetime.now(timezone.utc).isoformat()}
            found += 1
            tag = f"OK {std}"
        print(f"  [{i+1}/{len(todo)}] {m['brand']:11} {m['model'][:30]:32} {tag}")
    CURATED.write_text(json.dumps(cur, indent=1, ensure_ascii=False))
    print(f"\n[scan] {found}/{len(todo)} unflagged bikes have a UL/EN cert in page prose -> {CURATED}")


if __name__ == "__main__":
    main()
