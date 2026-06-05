#!/usr/bin/env python3
"""
Estimate the component (bill-of-materials) cost of every scraped e-bike.

Scans all *_ebikes.json files, reads each model's specs, and applies a
transparent heuristic cost model to the components it can identify (battery,
motor, brakes, drivetrain, fork, display, frame, wheels, …). Writes
`component_cost_estimates.json` with a per-component breakdown, an estimated
total, and the implied share of the retail price.

These are ROUGH wholesale/BOM estimates for comparison only -- not actual costs.

Usage: python estimate_component_costs.py [-o component_cost_estimates.json]
"""
from __future__ import annotations

import argparse
import glob
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spec_groups import flatten_grouped

HERE = Path(__file__).parent
DATA = HERE / "data"


def num(pattern: str, text: str) -> float | None:
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else None


def find_spec(specs: dict, *keywords) -> str:
    """Return the concatenated values of spec rows whose label matches any keyword."""
    hits = []
    for label, value in specs.items():
        low = label.lower()
        if any(k in low for k in keywords):
            hits.append(str(value))
    return " | ".join(hits)


# ------------------------- per-component cost estimators -------------------------

def cost_battery(specs):
    blob = find_spec(specs, "battery", "cell")
    wh = num(r"(\d{3,4}(?:\.\d+)?)\s*wh", blob)
    if wh is None:
        v = num(r"(\d{2,3}(?:\.\d+)?)\s*v", blob)
        ah = num(r"(\d{1,2}(?:\.\d+)?)\s*ah", blob)
        if v and ah:
            wh = v * ah
    if wh is None:
        return None, "no battery spec"
    base = round(wh * 0.42)                      # ~$0.42/Wh wholesale cell+pack
    if re.search(r"samsung|lg|panasonic|21700", blob, re.I):
        base = round(base * 1.1)
    return base, f"{round(wh)}Wh @ ~$0.42/Wh"


def cost_motor(specs):
    blob = find_spec(specs, "motor", "drive", "hub")
    if not blob:
        return None, "no motor spec"
    w = num(r"(\d{3,4})\s*w", blob)
    mid = bool(re.search(r"mid[- ]?drive|bottom bracket", blob, re.I))
    premium = bool(re.search(r"bosch|brose|specialized|shimano ep|yamaha|ultro", blob, re.I))
    if mid:
        c = 230 + (w or 500) * 0.20
        note = "mid-drive"
    else:
        c = 70 + (w or 500) * 0.11
        note = "hub motor"
    if premium:
        c += 180
        note += " (premium brand)"
    return round(c), note


def cost_brakes(specs):
    blob = find_spec(specs, "brake")
    if not blob:
        return None, "no brake spec"
    if re.search(r"hydraulic", blob, re.I):
        c, note = 95, "hydraulic disc"
    elif re.search(r"mechanical|cable", blob, re.I):
        c, note = 38, "mechanical disc"
    else:
        c, note = 60, "disc brakes"
    if re.search(r"4[- ]?piston|four[- ]?piston", blob, re.I):
        c += 35; note += ", 4-piston"
    return c, note


def cost_drivetrain(specs):
    blob = find_spec(specs, "drivetrain", "derailleur", "shift", "transmission",
                     "cassette", "freewheel", "gear", "chain")
    if not blob:
        return None, "no drivetrain spec"
    if re.search(r"belt|gates|carbon drive", blob, re.I) or \
       re.search(r"enviolo|cvt|nuvinci|igh|internal gear|auto[- ]?shift", blob, re.I):
        return 320, "belt / internally-geared / CVT"
    if re.search(r"single[- ]?speed", blob, re.I):
        return 30, "single-speed"
    sp = num(r"(\d{1,2})[- ]?speed", blob)
    return round(45 + (sp or 7) * 6), f"{int(sp) if sp else '~7'}-speed derailleur"


def cost_fork(specs):
    blob = find_spec(specs, "fork", "suspension")
    if not blob:
        return None, "no fork spec"
    if re.search(r"\bair\b", blob, re.I):
        return 175, "air suspension fork"
    if re.search(r"full[- ]?suspension|rear (spring|shock)|horst", blob, re.I):
        return 240, "full suspension"
    if re.search(r"suspension|hydraulic|coil|lock[- ]?out", blob, re.I):
        return 95, "suspension fork"
    return 45, "rigid fork"


def cost_display(specs):
    blob = find_spec(specs, "display", "ui", "screen")
    if not blob:
        return None, "no display spec"
    if re.search(r"bosch|kiox|mastermind|tft", blob, re.I) or re.search(r"color", blob, re.I):
        return 65, "color/TFT display"
    return 28, "LCD display"


def cost_frame(specs):
    blob = find_spec(specs, "frame")
    if re.search(r"carbon", blob, re.I):
        return 520, "carbon frame"
    if re.search(r"steel|cr-?mo", blob, re.I):
        return 150, "steel frame"
    return 200, "aluminum frame"   # default assumption for an e-bike frame


def cost_tires(specs):
    blob = find_spec(specs, "tire", "tyre")
    if not blob:
        return 55, "tires (assumed)"
    fat = re.search(r"[34](?:\.\d)?\s*[\"”']|fat", blob, re.I)
    return (80, "fat tires") if fat else (55, "tires")


def simple(specs, keywords, cost, label):
    return (cost, label) if find_spec(specs, *keywords) else (None, None)


# Components estimated only if their spec is present.
SPEC_DRIVEN = {
    "battery": cost_battery,
    "motor": cost_motor,
    "brakes": cost_brakes,
    "drivetrain": cost_drivetrain,
    "fork_suspension": cost_fork,
    "display": cost_display,
    "tires": cost_tires,
    "lights": lambda s: simple(s, ("light", "headlight", "taillight"), 30, "lights"),
    "fenders": lambda s: simple(s, ("fender",), 25, "fenders"),
    "rack": lambda s: simple(s, ("rack",), 35, "rear rack"),
    "kickstand": lambda s: simple(s, ("kickstand",), 12, "kickstand"),
    "throttle": lambda s: simple(s, ("throttle",), 15, "throttle"),
    "sensor": lambda s: simple(s, ("sensor",), 35, "torque/cadence sensor"),
    "charger": lambda s: simple(s, ("charger",), 35, "charger"),
    "controller": lambda s: simple(s, ("controller",), 40, "controller"),
    "saddle_seatpost": lambda s: simple(s, ("saddle", "seatpost", "seat post"), 45, "saddle/seatpost"),
    "cockpit": lambda s: simple(s, ("handlebar", "stem", "grip"), 40, "handlebar/stem/grips"),
    "wheels": lambda s: simple(s, ("wheel", "rim", "hub", "spoke"), 130, "wheelset"),
}
# Always-present components/labor not always itemised in specs.
FIXED = {"frame": cost_frame, "assembly_misc": lambda s: (120, "cables, bolts, assembly, packaging")}


def estimate(model: dict) -> dict:
    specs = model.get("specs", {}).get("all") \
        or flatten_grouped(model.get("specs", {}).get("grouped")) or {}
    breakdown, notes = {}, {}
    for name, fn in SPEC_DRIVEN.items():
        c, note = fn(specs)
        if c:
            breakdown[name] = c
            notes[name] = note
    for name, fn in FIXED.items():
        c, note = fn(specs)
        if c:
            breakdown[name] = c
            notes[name] = note
    total = sum(breakdown.values())
    # retail price across the varying brand schemas
    retail = model.get("price_from")
    if retail is None:
        pr = model.get("price_range") or {}
        retail = pr.get("min") or pr.get("max")
    if retail is None:
        retail = model.get("price")
    return {
        "component_costs": dict(sorted(breakdown.items(), key=lambda kv: -kv[1])),
        "notes": notes,
        "estimated_component_total": total,
        "retail_price": retail,
        "bom_pct_of_retail": round(total / retail, 3) if retail else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="data/component_cost_estimates.json")
    args = ap.parse_args()

    out_models = []
    for f in sorted(glob.glob(str(DATA / "*_ebikes.json"))):
        brand = Path(f).stem.replace("_ebikes", "")
        d = json.load(open(f))
        for m in d.get("models", []):
            name = m.get("model") or m.get("title") or m.get("handle")
            if not m.get("spec_count"):
                continue
            est = estimate(m)
            out_models.append({"brand": brand, "model": name,
                               "warranty": m.get("warranty"), **est})

    out_models.sort(key=lambda r: (r["brand"], r["model"]))
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": ("Rough wholesale/BOM cost ESTIMATES derived heuristically "
                       "from each bike's published specs. For comparison only; not "
                       "actual manufacturer costs."),
        "model_count": len(out_models),
        "models": out_models,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {args.output} ({len(out_models)} models).")


if __name__ == "__main__":
    main()
