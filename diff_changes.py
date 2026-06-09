#!/usr/bin/env python3
"""
Daily change-log: diff the freshly-built normalized fleet against the previous
build and record what changed per model.

Runs as the LAST pipeline stage (after analyze.py + audit.py), comparing the
current `data/current/active/ebikes_normalized.json` to the most-recent archived
build in `data/legacy/<date>/ebikes_normalized.json` (run_scrape.sh archives the
prior build there before each run). Models are matched by their stable `id`
(`brand__handle`). Tracked changes:

  * new / removed   -- a model id appeared / disappeared
  * price           -- the headline price moved (from/to/delta/pct)
  * sale            -- on-sale started / ended / deepened (discount % grew)
  * free_feature    -- a $0 bundled feature/accessory (or free shipping) added/removed
  * stock           -- availability flipped (back_in_stock / sold_out)

Outputs (pure-compute, no network, idempotent against a fixed baseline):
  - data/current/changes.json        -- summary + the full change list
  - data/changes/<date>.json         -- dated history copy
  - per-model `changed_today` stamp written back into ebikes_normalized.json
    (so the web can render "Price drop" / "On sale" / "New" / "Back in stock"
    badges with no extra fetch); omitted when a model didn't change.

Usage:  python diff_changes.py [-i ebikes_normalized.json] [--baseline <path>]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"
ACTIVE = DATA / "current" / "active" / "ebikes_normalized.json"


# ----------------------------- field accessors ------------------------------

def _price(m: dict):
    p = (m.get("pricing") or {}).get("price")
    return p if p is not None else (m.get("price") if m.get("price") is not None else m.get("price_min"))


def _on_sale(m: dict) -> bool:
    return bool((m.get("pricing") or {}).get("on_sale"))


def _discount_pct(m: dict):
    return (m.get("pricing") or {}).get("discount_pct")


def _status(m: dict):
    return (m.get("availability") or {}).get("status")


def _free_features(m: dict) -> dict:
    """lowercased name -> display name for every $0 bundled feature, plus a
    'Free shipping' pseudo-feature, so additions/removals can be diffed."""
    out: dict = {}
    for a in (m.get("free_accessories") or []):
        n = (a.get("name") or "").strip()
        if n:
            out[n.lower()] = n
    for a in (m.get("included_accessories") or []):
        n = (a.get("name") or "").strip()
        if n:
            out.setdefault(n.lower(), n)
    if m.get("shipping_free"):
        out["free shipping"] = "Free shipping"
    return out


# ------------------------------- diff engine --------------------------------

def diff_model(cur: dict, base: dict) -> dict:
    """Return {type: detail, ...} for everything that changed on one model."""
    ch: dict = {}

    pc, pb = _price(cur), _price(base)
    if pc is not None and pb is not None and pc != pb:
        delta = round(pc - pb, 2)
        ch["price"] = {
            "from": pb, "to": pc, "delta": delta,
            "pct": round(delta / pb * 100) if pb else None,
            "direction": "drop" if delta < 0 else "rise",
        }

    sc, sb = _on_sale(cur), _on_sale(base)
    dc, db = _discount_pct(cur), _discount_pct(base)
    if sc and not sb:
        ch["sale"] = {"event": "started", "discount_pct": dc}
    elif sb and not sc:
        ch["sale"] = {"event": "ended"}
    elif sc and sb and dc is not None and db is not None and dc != db:
        ch["sale"] = {"event": "deepened" if dc > db else "reduced",
                      "from_pct": db, "to_pct": dc}

    fc, fb = _free_features(cur), _free_features(base)
    added = [fc[k] for k in fc.keys() - fb.keys()]
    removed = [fb[k] for k in fb.keys() - fc.keys()]
    if added or removed:
        ch["free_feature"] = {"added": sorted(added), "removed": sorted(removed)}

    stc, stb = _status(cur), _status(base)
    if stc != stb and stb is not None and stc is not None:
        if stb == "sold_out" and stc == "in_stock":
            ch["stock"] = {"event": "back_in_stock"}
        elif stb == "in_stock" and stc == "sold_out":
            ch["stock"] = {"event": "sold_out"}
    return ch


def build_changes(current: list, baseline: list) -> tuple[list, list]:
    """Return (rows, removed_rows). `rows` covers new + per-field changes on
    surviving models; `removed_rows` are baseline ids gone from the build."""
    base_by_id = {m.get("id"): m for m in baseline}
    cur_ids = set()
    rows: list = []
    for m in current:
        mid = m.get("id")
        cur_ids.add(mid)
        base = base_by_id.get(mid)
        if base is None:
            entry = {"id": mid, "brand": m.get("brand"), "model": m.get("model"),
                     "types": ["new"], "detail": {}}
            m["changed_today"] = {"types": ["new"], "detail": {}}
            rows.append(entry)
            continue
        ch = diff_model(m, base)
        if ch:
            types = list(ch.keys())
            m["changed_today"] = {"types": types, "detail": ch}
            rows.append({"id": mid, "brand": m.get("brand"), "model": m.get("model"),
                         "types": types, "detail": ch})
    removed = [{"id": b.get("id"), "brand": b.get("brand"), "model": b.get("model"),
                "types": ["removed"]}
               for mid, b in base_by_id.items() if mid not in cur_ids]
    return rows, removed


def find_baseline(current_date: str) -> Path | None:
    """Most-recent archived build; prefer one dated before today's build."""
    dirs = sorted(p for p in glob.glob(str(DATA / "legacy" / "*"))
                  if Path(p, "ebikes_normalized.json").exists())
    if not dirs:
        return None
    before = [p for p in dirs if Path(p).name < current_date]
    chosen = (before or dirs)[-1]
    return Path(chosen, "ebikes_normalized.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diff the current build against the previous one.")
    ap.add_argument("-i", "--input", default=str(ACTIVE))
    ap.add_argument("--baseline", default=None, help="explicit baseline normalized json")
    ap.add_argument("--json", default=str(DATA / "current" / "changes.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    models = doc.get("models", [])
    gen = (doc.get("generated_at") or datetime.now(timezone.utc).isoformat())
    today = gen[:10]

    base_path = Path(args.baseline) if args.baseline else find_baseline(today)
    if base_path and base_path.exists():
        baseline = json.load(open(base_path)).get("models", [])
        baseline_date = re.search(r"\d{4}-\d{2}-\d{2}", str(base_path))
        baseline_date = baseline_date.group(0) if baseline_date else None
    else:
        baseline = []
        baseline_date = None

    rows, removed = build_changes(models, baseline)

    by_type: dict = {}
    for r in rows + removed:
        for t in r["types"]:
            by_type[t] = by_type.get(t, 0) + 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_date": today,
        "baseline_date": baseline_date,
        "summary": {
            "models_changed": len(rows),
            "removed": len(removed),
            "by_type": by_type,
        },
        "changes": rows + removed,
    }

    Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    hist_dir = DATA / "changes"
    hist_dir.mkdir(parents=True, exist_ok=True)
    (hist_dir / f"{today}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    # per-model changed_today stamps were set during build_changes
    Path(args.input).write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    if baseline_date is None:
        print("[*] diff_changes: no prior build to compare against (first run) — empty change-log.")
    else:
        print(f"[*] diff_changes vs {baseline_date}: {len(rows)} models changed, "
              f"{len(removed)} removed.  by_type={by_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
