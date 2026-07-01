#!/usr/bin/env python3
"""
Estimate the component (bill-of-materials) cost of every scraped e-bike.

Applies a transparent, brand/tier-aware heuristic model to estimate the RETAIL
(aftermarket street/replacement) price of the components it can identify (battery,
motor, brakes, drivetrain, fork, display, frame, wheels, …). Brand drives the
estimate as much as the spec — a Bosch system battery or a Fox fork costs far
more than a generic equivalent.

The per-component `cost_*` functions are the project's single retail estimator,
reused by resolve_component_prices.heuristic_retail to price any catalog part
that lacks a researched price. (The standalone per-bike report this module used
to write is no longer part of the pipeline.)

These are ROUGH retail estimates for comparison only -- not actual prices.

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
from parse_components import battery_system_wh

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

# A battery's retail/replacement price is driven by BRAND as much as by capacity.
# Proprietary system batteries (Bosch PowerTube, Specialized SL, Shimano STEPS, …) run
# far above a generic pack; a pack built on premium 21700 cells (LG/Samsung/Panasonic/
# Molicel) costs more than a no-name pack. Tiered $/Wh below; a Bosch 625Wh PowerTube
# lands ~$810 (matches its ~$700-850 street price), a generic 720Wh ~$324.
# Drive-system brands AND big OEMs that sell their own proprietary integrated packs
# (Giant EnergyPak, Trek RIB, Cannondale, etc.) — all priced like a system battery, not
# the generic DTC packs (Aventon/Lectric/…) that correctly fall to the cell-based tiers.
_SYSTEM_BATTERY = re.compile(
    r"bosch|brose|specialized|shimano|yamaha|fazua|mahle|\btq\b|darfon"
    r"|giant|energypak|trek|cannondale|gazelle|riese|haibike|\bcube\b|orbea|canyon", re.I)
_PREMIUM_CELL = re.compile(r"samsung|\blg\b|panasonic|molicel|sanyo|murata|21700", re.I)


def cost_battery(specs):
    blob = find_spec(specs, "battery", "cell")
    per_pack, total_wh, count = battery_system_wh(blob)
    if total_wh is None:                          # no Wh figure -> derive from V·Ah
        v = num(r"(\d{2,3}(?:\.\d+)?)\s*v", blob)
        ah = num(r"(\d{1,2}(?:\.\d+)?)\s*ah", blob)
        if v and ah:
            per_pack = v * ah
            total_wh = per_pack * count
    if total_wh is None:
        return None, "no battery spec"
    if _SYSTEM_BATTERY.search(blob):
        rate, tier = 1.30, "system-brand pack"
    elif _PREMIUM_CELL.search(blob):
        rate, tier = 0.65, "premium cells"
    else:
        rate, tier = 0.45, "generic cells"
    base = round(total_wh * rate)
    note = f"{round(total_wh)}Wh @ ~${rate:.2f}/Wh ({tier})"
    if count > 1 and per_pack and total_wh != per_pack:
        note += f" ({count}×{round(per_pack)}Wh)"
    return base, note


# Premium mid-drive systems command a big retail premium; Bafang M-series are mid-drives
# but mid-tier, so they get mid-drive (torque-driven) pricing WITHOUT the premium bump.
_PREMIUM_MOTOR = re.compile(r"bosch|brose|specialized\s*(2\.|sl|turbo)|shimano\s*(ep|steps|e\d)"
                            r"|yamaha|\btq\b|fazua|mahle|ultro", re.I)
_MID_MOTOR = re.compile(r"mid[- ]?drive|bottom bracket|bafang\s*m\d", re.I)


def cost_motor(specs):
    blob = find_spec(specs, "motor", "drive", "hub")
    if not blob:
        return None, "no motor spec"
    w = num(r"(\d{3,4})\s*w", blob)
    nm = num(r"(\d{2,3})\s*n\W{0,2}m", blob)        # 120Nm / 85 N.m
    mid = bool(_MID_MOTOR.search(blob) or _PREMIUM_MOTOR.search(blob))
    premium = bool(_PREMIUM_MOTOR.search(blob))
    if mid:
        # torque tracks a mid-drive's tier/cost better than wattage (a 120Nm unit is
        # pricier than a 65Nm one); fall back to wattage only when torque is unknown.
        if nm:
            c, note = 140 + nm * 3.3, f"mid-drive {int(nm)}Nm"
        else:
            c, note = 230 + (w or 500) * 0.20, "mid-drive"
        if premium:
            c += 180; note += " (premium brand)"
    else:
        c, note = 70 + (w or 500) * 0.11, "hub motor"
        if premium:
            c += 120; note += " (premium brand)"
    return round(c), note


# Premium brake families (4-piston/quality hydraulic) that retail well above a generic disc.
_PREMIUM_BRAKE = re.compile(r"magura|deore|\bxtr?\b|\bslx\b|sram\s*(code|guide|level|db8)"
                            r"|\btrp\b|\bhope\b|\bhayes\b|formula|tektro\s*(orion|hd-?e[4-9])", re.I)


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
    if re.search(r"(?:4|four|quad)[- ]?piston", blob, re.I):
        c += 35; note += ", 4-piston"
    # flagship stoppers (SRAM Maven, Magura Gustav/MT7) retail ~$260/wheel — well above
    # the generic premium bump; price them as top-tier.
    if re.search(r"\bmaven\b|gustav|\bmt7\b", blob, re.I):
        c += 130; note += ", top-tier"
    elif _PREMIUM_BRAKE.search(blob):
        c += 40; note += ", premium"
    return c, note


def cost_drivetrain(specs):
    blob = find_spec(specs, "drivetrain", "derailleur", "shift", "transmission",
                     "cassette", "freewheel", "gear", "chain")
    if not blob:
        return None, "no drivetrain spec"
    if re.search(r"pinion|rohloff", blob, re.I):           # sealed premium gearbox
        return 650, "premium gearbox (Pinion/Rohloff)"
    # internally-geared / CVT hubs are premium (whether belt- or chain-driven)
    if re.search(r"enviolo|\bcvt\b|nuvinci|\bigh\b|internal gear|nexus|alfine|auto[- ]?shift", blob, re.I):
        return 320, "internally-geared / CVT"
    # a SINGLE-SPEED drive is cheap — a belt (Gates) costs more than a single-speed chain.
    # Check this BEFORE the generic belt branch so a single-speed belt isn't priced as IGH.
    if re.search(r"single[- ]?speed", blob, re.I):
        belt = bool(re.search(r"belt|gates|carbon drive", blob, re.I))
        return (140, "single-speed belt") if belt else (30, "single-speed")
    if re.search(r"belt|gates|carbon drive", blob, re.I):  # geared belt (usually belt+IGH)
        return 320, "belt drive"
    sp = num(r"(\d{1,2})[- ]?speed", blob)
    c, note = 45 + (sp or 7) * 6, f"{int(sp) if sp else '~7'}-speed derailleur"
    if re.search(r"\bxtr\b|\bxx1\b|\bx01\b|axs|\bdi2\b", blob, re.I):
        c += 160; note += " (flagship)"
    elif re.search(r"deore xt|\bxt\b|\bslx\b|gx eagle|\bgx\b", blob, re.I):
        c += 90; note += " (high-end)"
    elif re.search(r"deore|advent x|\bnx\b|cues", blob, re.I):
        c += 35; note += " (mid)"
    return round(c), note


# Premium suspension makers (air forks/shocks that retail well above generic coil).
_PREMIUM_FORK = re.compile(r"\bfox\b|rock\s*shox|marzocchi|öhlins|ohlins|\bdvo\b|dt\s*swiss"
                           r"|suntour\s*(axon|durolux|rux)", re.I)


def cost_fork(specs):
    blob = find_spec(specs, "fork", "suspension")
    if not blob:
        return None, "no fork spec"
    prem = bool(_PREMIUM_FORK.search(blob))
    if re.search(r"\bair\b", blob, re.I):
        return (350, "premium air fork") if prem else (185, "air suspension fork")
    if re.search(r"full[- ]?suspension|rear (spring|shock)|horst", blob, re.I):
        return 240, "full suspension"
    if re.search(r"carbon", blob, re.I):
        return 150, "carbon rigid fork"
    if re.search(r"suspension|hydraulic|coil|lock[- ]?out|travel", blob, re.I):
        return (210, "premium coil fork") if prem else (95, "suspension fork")
    return 45, "rigid fork"


def cost_shock(specs):
    """Rear shock (the damper that makes a bike full-suspension) — priced separately
    from the front fork. Premium makers (Fox/RockShox/Öhlins) cost well above a budget
    OEM air/coil shock."""
    blob = find_spec(specs, "rear_shock", "shock", "suspension")
    if not blob:
        return None, "no shock spec"
    prem = bool(_PREMIUM_FORK.search(blob))
    if re.search(r"\bair\b", blob, re.I):
        return (300, "premium air shock") if prem else (170, "air rear shock")
    if re.search(r"coil|spring", blob, re.I):
        return (260, "premium coil shock") if prem else (120, "coil rear shock")
    return (260, "premium rear shock") if prem else (150, "rear shock")


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
    ap.add_argument("-o", "--output", default="data/current/component_cost_estimates.json")
    args = ap.parse_args()

    out_models = []
    for f in sorted(glob.glob(str(DATA / "current" / "*_ebikes.json"))):
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
        "disclaimer": ("Rough RETAIL price ESTIMATES derived heuristically (brand/spec-"
                       "aware) from each bike's published specs. For comparison only; "
                       "not actual prices."),
        "model_count": len(out_models),
        "models": out_models,
    }
    Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Wrote {args.output} ({len(out_models)} models).")


if __name__ == "__main__":
    main()
