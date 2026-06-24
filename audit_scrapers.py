#!/usr/bin/env python3
"""
Per-scraper field audit + resolution log.

For every brand's models it checks the card ICON tiles + cost/spec CORE fields, records
each (model, field) as present / open / needs-image / unpublished, and persists a
per-scraper log that tracks issues ACROSS runs (first_flagged -> resolved_at). With
--resolve it first runs the missing-field resolver (whole-HTML widening) so gaps get a
real extraction attempt before being logged.

It duplicates NO field logic or extraction:
  - audit.py                              -> field set, labels, presence test, known-absent
  - analysis.specs_typed (active build)   -> a field's current value + presence
  - model.html_extracted                  -> field was filled by the resolver (vs scraped)
  - data/curated/html_extracted.json      -> resolver values not yet folded in (pre-rebuild)
  - data/current/missing_resolution_report.json -> why an unresolved field failed:
        "no candidate ..." -> not in ANY page HTML -> needs image / likely unpublished
        "ambiguous: [...]" -> conflicting values on the page -> open, needs a rule

Status per (model, field):
  present       value in the build, from the scraper
  resolved      value from the resolver (html_extracted), source tagged
  open          missing; the resolver had no/ambiguous answer (still actionable in text)
  needs_image   missing; not in any HTML -> try an image/curated override next
  unpublished   listed in known_absent.json -> verified not published anywhere

Output: data/audits/<brand>.json  (+ a console summary).

Usage:
  python audit_scrapers.py                       # offline: audit current build, refresh logs
  python audit_scrapers.py --brand velowave
  python audit_scrapers.py --resolve [--brand X] # run the resolver first (network), then audit
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import audit  # reuse the field set, labels, presence test and known-absent exclusions

HERE = Path(__file__).parent
ACTIVE = HERE / "data" / "current" / "active" / "ebike.json"
REPORT = HERE / "data" / "current" / "missing_resolution_report.json"
HTML_EXTRACTED = HERE / "data" / "curated" / "html_extracted.json"
AUDIT_DIR = HERE / "data" / "audits"

# The fields this audit cares about: the card's icon tiles + the spec/cost core.
# (a subset of audit.EXPECTED_FIELDS; the motor tile accepts nominal OR peak watts.)
ICON_CORE = [
    "motor_w", "battery_wh", "torque_nm", "max_speed_mph", "range_mi", "weight_lb",
    "max_load_lb", "fit_height_min_in", "sensor_type", "brake_type", "frame_material", "drive_type",
]
_LABELS = dict(audit.EXPECTED_FIELDS)
_TODAY = date.today().isoformat()

ISSUE = {"open", "needs_image"}
RESOLVED = {"present", "resolved"}


def _value(typed: dict, key: str):
    if key == "motor_w":
        return typed.get("motor_w") or typed.get("motor_peak_w")
    return typed.get(key)


def _present(typed: dict, key: str) -> bool:
    return audit._present(_value(typed, key))


def _report_reasons() -> dict[tuple[str, str], str]:
    """(url, field) -> reason, from the resolver's unresolved list."""
    try:
        rep = json.loads(REPORT.read_text())
    except (FileNotFoundError, ValueError):
        return {}
    return {(u["url"], u["field"]): u.get("reason", "") for u in rep.get("unresolved", [])}


def _html_extracted() -> dict:
    try:
        return json.loads(HTML_EXTRACTED.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _status(model: dict, key: str, reasons: dict, he: dict) -> dict:
    """Classify one (model, field): status, source, value, note."""
    typed = audit._typed(model)
    mid, url = model.get("id", ""), model.get("url", "")
    if key in audit._absent(model):
        return {"status": "unpublished", "source": "known_absent", "value": None, "note": ""}
    if _present(typed, key):
        from_html = key in (model.get("html_extracted") or [])
        return {"status": "resolved" if from_html else "present",
                "source": "html_extracted" if from_html else "scraped",
                "value": _value(typed, key), "note": ""}
    # resolver found it this run but the build isn't rebuilt yet
    hit = (he.get(mid) or {}).get(key)
    if hit:
        return {"status": "resolved", "source": "html_extracted",
                "value": hit.get("value"), "note": "pending rebuild"}
    reason = reasons.get((url, key), "")
    if reason.startswith("no candidate"):
        return {"status": "needs_image", "source": None, "value": None, "note": reason}
    return {"status": "open", "source": None, "value": None, "note": reason}


def _merge(prev: dict, cur: dict) -> dict:
    """Carry first_flagged / resolved_at across runs so the log tracks each issue's life."""
    out = dict(cur)
    out["first_flagged"] = prev.get("first_flagged")
    out["resolved_at"] = prev.get("resolved_at")
    was_issue = prev.get("status") in ISSUE
    if cur["status"] in ISSUE:
        out["first_flagged"] = out["first_flagged"] or _TODAY
        out["resolved_at"] = None
    elif cur["status"] in RESOLVED and was_issue:
        out["resolved_at"] = _TODAY            # just got filled
    return out


def audit_brand(brand: str, models: list, reasons: dict, he: dict) -> dict:
    path = AUDIT_DIR / f"{brand}.json"
    try:
        prev = {m["id"]: m for m in json.loads(path.read_text())["models"]}
    except (FileNotFoundError, ValueError, KeyError):
        prev = {}
    out_models, tally = [], Counter()
    for m in sorted(models, key=lambda x: x.get("model") or ""):
        mid = m.get("id", "")
        prev_fields = (prev.get(mid) or {}).get("fields", {})
        fields = {}
        for key in ICON_CORE:
            cur = _status(m, key, reasons, he)
            fields[key] = _merge(prev_fields.get(key, {}), cur)
            tally[cur["status"]] += 1
        out_models.append({"id": mid, "model": m.get("model"), "url": m.get("url"), "fields": fields})
    doc = {
        "brand": brand, "scraper": f"scrape_{brand}.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fields_audited": ICON_CORE,
        "summary": {"models": len(models), **{k: tally.get(k, 0) for k in
                    ("present", "resolved", "open", "needs_image", "unpublished")}},
        "models": out_models,
    }
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    return doc


def main():
    ap = argparse.ArgumentParser(description="Per-scraper key/icon-field audit + resolution log.")
    ap.add_argument("--brand", help="audit a single brand")
    ap.add_argument("--resolve", action="store_true",
                    help="run the missing-field resolver first (network), then audit")
    args = ap.parse_args()

    if args.resolve:
        cmd = [sys.executable, str(HERE / "resolve_missing_fields.py")]
        if args.brand:
            cmd += ["--brand", args.brand]
        print(f"[*] resolving missing fields first: {' '.join(cmd[1:])}", file=sys.stderr)
        subprocess.run(cmd, check=False)

    doc = json.loads(ACTIVE.read_text())
    models = doc.get("models", [])
    audit.audit(models)                       # annotate models (respects known_absent)
    reasons, he = _report_reasons(), _html_extracted()
    by_brand = defaultdict(list)
    for m in models:
        by_brand[m.get("brand", "")].append(m)
    brands = [args.brand] if args.brand else sorted(by_brand)

    print(f"{'brand':<14}{'models':>7}{'present':>9}{'resolved':>9}{'open':>6}{'needs_img':>10}{'unpub':>7}")
    tot = Counter()
    for b in brands:
        if b not in by_brand:
            print(f"  no models for brand {b!r}", file=sys.stderr); continue
        s = audit_brand(b, by_brand[b], reasons, he)["summary"]
        for k in ("present", "resolved", "open", "needs_image", "unpublished"):
            tot[k] += s[k]
        print(f"{b:<14}{s['models']:>7}{s['present']:>9}{s['resolved']:>9}"
              f"{s['open']:>6}{s['needs_image']:>10}{s['unpublished']:>7}")
    print(f"{'TOTAL':<14}{'':>7}{tot['present']:>9}{tot['resolved']:>9}"
          f"{tot['open']:>6}{tot['needs_image']:>10}{tot['unpublished']:>7}")
    print(f"[*] wrote per-scraper logs to {AUDIT_DIR}/<brand>.json")
    if args.resolve:
        print("[*] note: resolver values are credited from html_extracted.json; run "
              "./rebuild_offline.sh to fold them into the build.", file=sys.stderr)


if __name__ == "__main__":
    main()
