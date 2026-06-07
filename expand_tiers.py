#!/usr/bin/env python3
"""
Expand multi-price-tier e-bikes into sibling model entries.

Some models sell spec-bearing tiers under one product page — battery-size options
(Himiway "15Ah" vs "15Ah+20Ah"), single/dual-battery "Version"s (Heybike), and
Lectric's per-config builds. One entry with `price_from` + base specs makes the upper
tiers invisible or wrong downstream (search, BOM/value estimates, scores, compare).

This step rewrites data/current/*_ebikes.json in place (same precedent as the other
add_*.py steps), splitting each spec-bearing tier into its own model entry:
  - the base entry keeps its identity (stable id) and becomes the CHEAPEST tier,
  - siblings get `handle = <base>--<tier-slug>` and a tier-suffixed model name,
  - both carry `tier` (label) and `family_id` (= the base entry's normalized id),
  - each entry's `configurations` are filtered to its own tier, so prices are right,
  - where derivable, the battery spec text is patched so the existing parser chain
    (parse_components.battery_system_wh, analyze, estimate) computes correct numbers.

Color-only and frame-size price differences are deliberately NOT expanded — those
stay one model (the UI's color swatches handle them).

Idempotent: models already carrying `tier` are skipped.

Run after add_pricing.py, before normalize.py (run_scrape.sh wires this).
"""
import copy
import glob
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data"

# Option keys that denote a real spec/build tier when they drive distinct prices.
# Strict full-match allowlist: looks/fit keys (color, size, frame-type) and junk keys
# never match, so they can never split a model.
TIER_KEY = re.compile(
    r"^(battery[\s_-]?size|version|drive[\s_-]?train|package|bike[\s_-]?type"
    r"|variant|type)$", re.I)


def slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def base_source_id(m: dict) -> str:
    name = m.get("model") or m.get("title") or m.get("name") or m.get("handle")
    return (m.get("handle") or m.get("slug") or m.get("sku") or slugify(name) or "")


# ----------------------------- battery spec patching -----------------------------

def _battery_row(specs_all: dict):
    for k, v in (specs_all or {}).items():
        if "batter" in k.lower() and isinstance(v, str) and re.search(r"\d", v):
            return k
    return None


def patched_battery_text(text: str, tier_value: str):
    """New battery row text for this tier, or None when nothing is derivable.

    1. Ah-style values ("15Ah", "15Ah+20Ah"): rebuild the figures around the tier's
       (combined) Ah at the pack voltage; dual setups gain an explicit
       "(...Wh) combined dual battery" so battery_system_wh treats it as the total.
    2. Version-style values where the base text embeds per-version Wh
       ("956.8Wh (Single Battery Ver.)1913.6Wh (Dual Battery Ver.)"): pick the Wh
       figure attached to this tier's label.
    """
    text = text or ""
    ahs = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*A[hH]", tier_value)]
    if ahs:
        total_ah = sum(ahs)
        vm = re.search(r"(\d{2,3})\s*V\b", text, re.I)
        volts = float(vm.group(1)) if vm else 48.0
        total_wh = round(volts * total_ah)
        label = (f"{total_ah:g}Ah ({total_wh}Wh) combined dual battery"
                 if len(ahs) > 1 else f"{total_ah:g}Ah ({total_wh}Wh)")
        # drop any pre-existing Wh figure first so the new one is unambiguous
        cleaned = re.sub(r"\(?\s*\d{3,4}(?:\.\d+)?\s*W[hH]\s*\)?", "", text)
        if re.search(r"\d+(?:\.\d+)?\s*A[hH]", cleaned):
            return re.sub(r"\d+(?:\.\d+)?\s*A[hH]", label, cleaned, count=1)
        return (cleaned.strip(" ,;") + " — " if cleaned.strip() else "") + label
    m = re.search(r"(\d{3,4}(?:\.\d+)?)\s*W[hH]\s*\(\s*" + re.escape(tier_value),
                  text, re.I)
    if m:
        return f"{m.group(1)}Wh total — {tier_value}"
    return None


def apply_battery_patch(model: dict, tier_value: str) -> None:
    specs = model.get("specs") or {}
    row = _battery_row(specs.get("all") or {})
    if not row:
        return
    new = patched_battery_text(specs["all"][row], tier_value)
    if not new:
        return
    for section in ("all", "physical", "technical"):
        sec = specs.get(section)
        if isinstance(sec, dict) and row in sec:
            sec[row] = new


# ------------------------------- tier detection -------------------------------

def tier_axis(cfgs: list):
    """(option_key, {value: price}) when one allowlisted option key cleanly drives
    2+ distinct prices, else None."""
    priced = [c for c in cfgs or [] if isinstance(c, dict) and c.get("price") is not None]
    if len({c["price"] for c in priced}) < 2:
        return None
    keys = {k for c in priced for k in (c.get("options") or {})}
    for k in sorted(keys):
        if not TIER_KEY.match(k.strip()):
            continue
        v2p: dict = {}
        for c in priced:
            v = (c.get("options") or {}).get(k)
            if v is not None:
                v2p.setdefault(str(v), set()).add(c["price"])
        if len(v2p) < 2:
            continue
        # Tier on the cheapest price per value (a colour upcharge inside a tier must
        # not block detection); valid when the tiers' base prices actually differ.
        mins = {v: min(ps) for v, ps in v2p.items()}
        if len(set(mins.values())) > 1:
            return k, mins
    return None


# ------------------------------- expansion -------------------------------

def make_sibling(base: dict, brand: str, tier_label: str) -> dict:
    sid = base_source_id(base)
    sib = copy.deepcopy(base)
    sib["handle"] = f"{sid}--{slugify(tier_label)}"
    name = base.get("model") or base.get("title") or base.get("name") or sid
    sib["model"] = f"{name} — {tier_label}"
    sib["regular_price"] = None  # family-level compare-at price doesn't apply per tier
    return sib


def expand_generic(brand: str, m: dict) -> list:
    axis = tier_axis(m.get("configurations") or [])
    if not axis:
        return [m]
    key, value_prices = axis
    fam = f"{brand}__{base_source_id(m)}"
    ordered = sorted(value_prices.items(), key=lambda kv: kv[1])
    out = []
    for i, (value, price) in enumerate(ordered):
        entry = m if i == 0 else make_sibling(m, brand, value)
        entry["tier"] = value
        entry["family_id"] = fam
        entry["price_from"] = price
        entry["configurations"] = [
            c for c in (m.get("configurations") or [])
            if str((c.get("options") or {}).get(key)) == value
        ]
        apply_battery_patch(entry, value)
        out.append(entry)
    return out


def expand_lectric(brand: str, m: dict) -> list:
    cfgs = [c for c in (m.get("configs") or []) if c.get("price") is not None]
    if len({c["price"] for c in cfgs}) < 2:
        return [m]
    fam = f"{brand}__{base_source_id(m)}"
    name = m.get("model") or ""

    def label_of(c, i=0):
        return (c.get("battery") or
                (c.get("label") or "").replace(name, "").strip(" -—") or
                f"config {i + 1}")

    # One entry per battery tier: frame styles (High-Step/Step-Thru) share a tier, so
    # collapse them — keep the cheapest config per tier label.
    by_tier: dict = {}
    for c in cfgs:
        t = label_of(c)
        if t not in by_tier or c["price"] < by_tier[t]["price"]:
            by_tier[t] = c
    if len(by_tier) < 2:
        return [m]
    ordered = sorted(by_tier.values(), key=lambda c: c["price"])
    out = []
    for i, c in enumerate(ordered):
        tier_label = label_of(c, i)
        entry = m if i == 0 else make_sibling(m, brand, tier_label)
        entry["tier"] = tier_label
        entry["family_id"] = fam
        # the config carries its own full data — use it verbatim
        if c.get("specs"):
            entry["specs"] = copy.deepcopy(c["specs"])
            entry["spec_count"] = len((c["specs"] or {}).get("all") or {})
        if c.get("geometry"):
            entry["geometry"] = copy.deepcopy(c["geometry"])
        if c.get("url"):
            entry["url"] = c["url"]
        if c.get("colors"):
            entry.setdefault("options", {})["colors"] = copy.deepcopy(c["colors"])
        if c.get("accessories"):
            entry["accessories"] = copy.deepcopy(c["accessories"])
        entry["price_range"] = {"min": c["price"], "max": c["price"],
                                "currency": (m.get("price_range") or {}).get("currency", "USD")}
        entry["configs"] = [copy.deepcopy(c)]
        out.append(entry)
    return out


def main():
    grand = 0
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        models = d.get("models", [])
        out, added = [], 0
        for m in models:
            if m.get("tier"):           # already expanded (idempotent re-runs)
                out.append(m)
                continue
            entries = (expand_lectric if brand == "lectric" else expand_generic)(brand, m)
            added += len(entries) - 1
            out.extend(entries)
        if added:
            d["models"] = out
            d["model_count"] = len(out)
            json.dump(d, open(f, "w"), indent=2, ensure_ascii=False)
            print(f"{brand:<10} expanded {added} tier sibling(s) -> {len(out)} models")
            grand += added
    print(f"total new tier entries: {grand}")


if __name__ == "__main__":
    main()
