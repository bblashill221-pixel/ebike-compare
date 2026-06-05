#!/usr/bin/env python3
"""
Build the analysis layer on top of the normalized e-bike dataset.

Reads `data/ebikes_normalized.json` (and the BOM estimates in
`data/component_cost_estimates.json`), and for every model derives:

  TIER 1 - `specs_typed`: predictable, unit-fixed, *searchable* fields parsed out
           of the free-text specs (battery_wh, torque_nm, range_mi, motor_w,
           weight_lb, warranty_years, brake_type, ...). One fixed type+unit per
           field across all models. Missing -> null (never coerced to 0).

  TIER 2 - value-added "how does it compare to the field" signals:
           `percentiles` (each numeric field's rank within the field, 0..1) and
           `scores` (transparent per-dimension 0-100). These are a quick compare
           aid only -- there is deliberately NO composite/overall score, so the
           site can rank purely on whichever criteria the user cares about.

The result is written back into `ebikes_normalized.json` (an `analysis` block per
model, plus a top-level `analysis_stats` with the field distributions). The raw
per-brand files and the rest of the normalized doc are untouched.

Usage:  python analyze.py [-i data/ebikes_normalized.json] [-c data/component_cost_estimates.json]
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from spec_parse import num, find_spec, blob, kg_to_lb, percentile_rank
from spec_groups import flatten_grouped

HERE = Path(__file__).parent
DATA = HERE / "data"

# Numeric typed fields that get a field-relative percentile. `weight_lb` is
# inverted (lighter ranks higher); the rest are higher-is-better.
NUMERIC_FIELDS = [
    "battery_wh", "motor_w", "motor_peak_w", "torque_nm",
    "range_mi", "weight_lb", "gears",
]
INVERTED = {"weight_lb"}

WARRANTY_SCORE = {1: 20, 2: 45, 3: 65, 4: 80}   # >=5 or Lifetime -> 100


# ----------------------------- TIER 1: typed specs -----------------------------

def _battery_wh(specs):
    txt = find_spec(specs, "battery", "cell")
    wh = num(r"(\d{3,4}(?:\.\d+)?)\s*wh", txt)
    if wh is None:
        v = num(r"(\d{2,3}(?:\.\d+)?)\s*v\b", txt)
        ah = num(r"(\d{1,2}(?:\.\d+)?)\s*ah", txt)
        if v and ah:
            wh = v * ah
    return round(wh) if wh else None


def _cell_brand(specs):
    txt = find_spec(specs, "battery", "cell").lower()
    for b in ("samsung", "lg", "panasonic", "molicel", "sony"):
        if b in txt:
            return b
    return "generic" if txt else None


def _motor_w(specs):
    txt = find_spec(specs, "motor", "drive", "hub")
    if not txt:
        return None, None
    # Pull peak first, then strip those mentions so they don't read as continuous.
    peak = num(r"(\d{3,4})\s*w\s*peak", txt) or num(r"peak[^0-9]{0,18}(\d{3,4})\s*w", txt)
    cont_txt = re.sub(r"\d{3,4}\s*w\s*peak", " ", txt, flags=re.I)
    cont_txt = re.sub(r"peak[^0-9]{0,18}\d{3,4}\s*w", " ", cont_txt, flags=re.I)
    cont = num(r"(\d{3,4})\s*w\b", cont_txt)
    return (round(cont) if cont else None), (round(peak) if peak else None)


def _torque_nm(specs):
    txt = find_spec(specs, "torque", "motor")
    nm = num(r"(\d{2,3})\s*n\W{0,2}m", txt)        # 80Nm | 105 N·m | 42nm
    return round(nm) if nm else None


def _drive_type(specs):
    txt = find_spec(specs, "motor", "drive").lower()
    if not txt:
        return None
    return "mid" if re.search(r"mid[- ]?drive|bottom bracket", txt) else "hub"


def _range_mi(specs):
    txt = find_spec(specs, "range")
    vals = [float(g) for g in re.findall(r"(\d{2,3})\s*(?:mile|mi\b)", txt, re.I)]
    if not vals:                                   # bare numbers in a range row
        vals = [float(g) for g in re.findall(r"\b(\d{2,3})\b", txt)]
    return round(max(vals)) if vals else None


def _weight_lb(specs):
    # Only the bike's own weight -- skip rider/payload/cargo/capacity rows, which
    # also quote pounds (e.g. "Recommended Rider Weight: <250lbs").
    bad = ("rider", "payload", "cargo", "recommended", "capacity", "load", "max")
    rows = {k: v for k, v in specs.items()
            if "weight" in k.lower() and not any(b in k.lower() for b in bad)}
    txt = find_spec(rows, "weight")
    lb = num(r"(\d{2,3}(?:\.\d+)?)\s*lb", txt)
    if lb is not None:
        return round(lb, 1)
    kg = num(r"(\d{2,3}(?:\.\d+)?)\s*kg", txt)
    return kg_to_lb(kg) if kg else None


def _brake_type(specs):
    txt = find_spec(specs, "brake").lower()
    if not txt:
        return None
    if "hydraulic" in txt:
        base = "hydraulic_disc"
    elif re.search(r"mechanical|cable", txt):
        base = "mechanical_disc"
    elif "disc" in txt:
        base = "disc"
    else:
        base = "rim"
    return base


def _drivetrain_type(specs):
    txt = find_spec(specs, "derailleur", "cassette", "chain", "drivetrain",
                    "shift", "gear", "transmission").lower()
    if not txt:
        return None
    if re.search(r"belt|gates|carbon drive", txt):
        return "belt"
    if re.search(r"enviolo|cvt|nuvinci|internal gear|igh|auto[- ]?shift", txt):
        return "internal_gear"
    if re.search(r"single[- ]?speed", txt):
        return "single_speed"
    return "derailleur"


def _gears(specs):
    txt = blob(specs)
    sp = num(r"(\d{1,2})[- ]?speed", txt)
    return int(sp) if sp else None


def _suspension(specs):
    txt = find_spec(specs, "fork", "suspension").lower()
    if not txt:
        return None
    if re.search(r"full[- ]?suspension|rear (spring|shock)|horst|dual suspension", txt):
        return "full"
    if re.search(r"\bair\b", txt):
        return "air_fork"
    if re.search(r"coil|spring|hydraulic|lock[- ]?out|suspension", txt):
        return "coil_fork"
    return "rigid"


def _frame_material(specs):
    txt = find_spec(specs, "frame").lower()
    if not txt:
        return None
    if "carbon" in txt:
        return "carbon"
    if re.search(r"steel|cr-?mo|chromoly", txt):
        return "steel"
    if re.search(r"alum|alloy|6061|aluminium", txt):
        return "aluminum"
    return None


def _sensor_type(specs):
    txt = find_spec(specs, "sensor", "motor").lower()
    if "torque" in txt:
        return "torque"
    if "cadence" in txt:
        return "cadence"
    return None


def _display_type(specs):
    txt = find_spec(specs, "display", "ui", "screen", "remote").lower()
    if not txt:
        return None
    if re.search(r"color|colour|tft|kiox|mastermind", txt):
        return "color_tft"
    if re.search(r"lcd|led|monochrome|backlit", txt):
        return "lcd"
    return "basic"


def _water_resistance(specs):
    m = re.search(r"\b(ip6\d|ipx\d)\b", blob(specs), re.I)
    return m.group(1).upper() if m else None


def _ul_listed(specs):
    return True if re.search(r"ul\s*-?\s*(2271|2849|2580)", blob(specs), re.I) else None


def _warranty_years(model):
    w = (model.get("warranty") or "").lower()
    if "lifetime" in w:
        return 99
    n = num(r"(\d+)\s*-?\s*year", w)
    return int(n) if n else None


def _connectivity(specs):
    b = blob(specs)
    flags = []
    if re.search(r"\bapp\b|smartphone|mobile app", b):
        flags.append("app")
    if "gps" in b:
        flags.append("gps")
    if "bluetooth" in b:
        flags.append("bluetooth")
    if re.search(r"alarm|anti[- ]?theft", b):
        flags.append("alarm")
    return flags


def _notable_tech(specs):
    b = blob(specs)
    out = []
    checks = [
        (r"regen", "regen braking"),
        (r"\babs\b", "ABS"),
        (r"belt|gates", "belt drive"),
        (r"dual[- ]?battery|second battery|two batteries", "dual-battery"),
        (r"anti[- ]?theft|gps tracking|alarm", "anti-theft"),
        (r"fingerprint", "fingerprint unlock"),
        (r"torque sensor", "torque sensor"),
        (r"mid[- ]?drive", "mid-drive motor"),
    ]
    for pat, label in checks:
        if re.search(pat, b):
            out.append(label)
    return out


def extract_typed_specs(model: dict) -> dict:
    # `specs` is the grouped map (group -> {field: value|parsed component});
    # flatten it back to a flat label->text map for the typed-fact regexes.
    specs = flatten_grouped(model.get("specs") or {})
    motor_w, motor_peak_w = _motor_w(specs)
    return {
        "battery_wh": _battery_wh(specs),
        "cell_brand": _cell_brand(specs),
        "removable_battery": True if re.search(r"removable", find_spec(specs, "battery"), re.I) else None,
        "motor_w": motor_w,
        "motor_peak_w": motor_peak_w,
        "torque_nm": _torque_nm(specs),
        "drive_type": _drive_type(specs),
        "range_mi": _range_mi(specs),
        "weight_lb": _weight_lb(specs),
        "brake_type": _brake_type(specs),
        "drivetrain_type": _drivetrain_type(specs),
        "gears": _gears(specs),
        "suspension": _suspension(specs),
        "frame_material": _frame_material(specs),
        "sensor_type": _sensor_type(specs),
        "display_type": _display_type(specs),
        "water_resistance": _water_resistance(specs),
        "ul_listed": _ul_listed(specs),
        "warranty_years": _warranty_years(model),
        "connectivity": _connectivity(specs),
        "notable_tech": _notable_tech(specs),
    }


# ------------------------ field distributions / stats ------------------------

def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    frac = pos - lo
    hi = min(lo + 1, len(sorted_vals) - 1)
    return round(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac, 2)


def build_stats(typed_by_id: dict) -> dict:
    """Per-numeric-field {min,p10,p50,p90,max,count} across the whole field."""
    stats = {}
    fields = NUMERIC_FIELDS + ["price", "bom_pct"]
    for field in fields:
        vals = sorted(v for v in (t.get(field) for t in typed_by_id.values())
                      if isinstance(v, (int, float)))
        if not vals:
            continue
        stats[field] = {
            "min": vals[0], "p10": _quantile(vals, 0.10),
            "p50": _quantile(vals, 0.50), "p90": _quantile(vals, 0.90),
            "max": vals[-1], "count": len(vals),
        }
    return stats


def _scale(value, st) -> float | None:
    """Map a value to 0-100 by its clamped p10..p90 position in the field."""
    if value is None or st is None:
        return None
    lo, hi = st["p10"], st["p90"]
    if hi == lo:
        return 50.0
    return round(max(0.0, min(1.0, (value - lo) / (hi - lo))) * 100, 1)


# ----------------------- TIER 2: percentiles + scores -----------------------

def compute_percentiles(typed: dict, sorted_field: dict) -> dict:
    out = {}
    for field in NUMERIC_FIELDS + ["price"]:
        v = typed.get(field)
        vals = sorted_field.get(field)
        if v is None or not vals:
            continue
        rank = percentile_rank(v, vals)
        if field in INVERTED or field == "price":   # lighter / cheaper ranks higher
            rank = round(1 - rank, 3)
        out[f"{field}_pct"] = rank
    return out


def _avg(*vals):
    have = [v for v in vals if v is not None]
    return round(sum(have) / len(have), 1) if have else None


def compute_scores(typed: dict, stats: dict, bom_pct, price_pct) -> dict:
    s = {}

    # --- numeric dimensions: the field-relative position, 0-100 ---
    s["power"] = _avg(_scale(typed.get("motor_w"), stats.get("motor_w")),
                      _scale(typed.get("torque_nm"), stats.get("torque_nm")))
    s["range"] = _scale(typed.get("range_mi"), stats.get("range_mi"))
    s["battery"] = _scale(typed.get("battery_wh"), stats.get("battery_wh"))

    # --- categorical dimensions: transparent additive rubrics (capped 100) ---
    comp = 0
    bt = typed.get("brake_type")
    comp += {"hydraulic_disc": 40, "mechanical_disc": 18, "disc": 20}.get(bt, 0)
    dt = typed.get("drivetrain_type")
    comp += {"belt": 25, "internal_gear": 25, "derailleur": 12, "single_speed": 4}.get(dt, 0)
    susp = typed.get("suspension")
    comp += {"full": 25, "air_fork": 20, "coil_fork": 10, "rigid": 0}.get(susp, 0)
    fm = typed.get("frame_material")
    comp += {"carbon": 15, "aluminum": 8, "steel": 5}.get(fm, 0)
    if typed.get("sensor_type") == "torque":
        comp += 15
    if typed.get("display_type") == "color_tft":
        comp += 10
    s["components"] = min(comp, 100) if (bt or dt or susp or fm) else None

    safety = 0
    safety += {"hydraulic_disc": 30, "mechanical_disc": 12, "disc": 18}.get(bt, 0)
    if "ABS" in typed.get("notable_tech", []):
        safety += 20
    if typed.get("ul_listed"):
        safety += 18
    if typed.get("water_resistance"):
        safety += 12
    if typed.get("sensor_type") == "torque":
        safety += 8
    s["safety"] = min(safety, 100) if (bt or typed.get("ul_listed")) else None

    conn = typed.get("connectivity", [])
    nt = typed.get("notable_tech", [])
    sec = 0
    if "gps" in conn:
        sec += 35
    if "alarm" in conn:
        sec += 25
    if "anti-theft" in nt:
        sec += 20
    if "fingerprint unlock" in nt:
        sec += 25
    if "app" in conn:
        sec += 15
    s["security"] = min(sec, 100)   # always present (0 = no security features found)

    tech = 0
    if "app" in conn:
        tech += 20
    if "gps" in conn:
        tech += 15
    if "regen braking" in nt:
        tech += 20
    if typed.get("display_type") == "color_tft":
        tech += 12
    if typed.get("sensor_type") == "torque":
        tech += 13
    if "belt drive" in nt:
        tech += 10
    if "dual-battery" in nt:
        tech += 10
    s["tech"] = min(tech, 100)

    wy = typed.get("warranty_years")
    if wy is None:
        s["warranty"] = None
    elif wy >= 5:
        s["warranty"] = 100
    else:
        s["warranty"] = WARRANTY_SCORE.get(wy, min(100, wy * 22))

    # --- value: BOM share of retail (rank) blended with cheaper-is-better ---
    if bom_pct is not None:
        v = bom_pct * 100
        if price_pct is not None:
            v = 0.7 * (bom_pct * 100) + 0.3 * (price_pct * 100)
        s["value"] = round(min(v, 100), 1)
    else:
        s["value"] = None

    return s


def _highlights(typed: dict) -> list:
    out = list(typed.get("notable_tech", []))
    if typed.get("sensor_type") == "torque" and "torque sensor" not in out:
        out.append("torque sensor")
    if typed.get("brake_type") == "hydraulic_disc":
        out.append("hydraulic brakes")
    if typed.get("frame_material") == "carbon":
        out.append("carbon frame")
    # de-dup, keep order
    seen, dedup = set(), []
    for h in out:
        if h not in seen:
            seen.add(h)
            dedup.append(h)
    return dedup


# --------------------------------- driver ---------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", default=str(DATA / "current" / "active" / "ebikes_normalized.json"))
    ap.add_argument("-c", "--costs", default=str(DATA / "current" / "component_cost_estimates.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    models = doc.get("models", [])

    # BOM lookup keyed by (brand, model name).
    bom = {}
    try:
        cd = json.load(open(args.costs))
        for r in cd.get("models", []):
            bom[(r.get("brand"), r.get("model"))] = r.get("bom_pct_of_retail")
    except FileNotFoundError:
        print(f"[!] {args.costs} not found; value scores will be null.")

    # Pass 1 - typed specs, plus price + bom folded in for the distributions.
    typed_by_id = {}
    for m in models:
        t = extract_typed_specs(m)
        t["price"] = m.get("price")
        t["bom_pct"] = bom.get((m.get("brand"), m.get("model")))
        typed_by_id[m["id"]] = t

    # Field distributions + the sorted value lists used for ranking.
    stats = build_stats(typed_by_id)
    sorted_field = {
        f: sorted(v for v in (t.get(f) for t in typed_by_id.values())
                  if isinstance(v, (int, float)))
        for f in NUMERIC_FIELDS + ["price", "bom_pct"]
    }

    # Pass 2 - percentiles + scores, written back into each model.
    for m in models:
        t = typed_by_id[m["id"]]
        bom_pct = t.pop("bom_pct")
        t.pop("price")                       # price already lives at model top level
        pct = compute_percentiles({**t, "price": m.get("price")}, sorted_field)
        bom_rank = (percentile_rank(bom_pct, sorted_field["bom_pct"])
                    if bom_pct is not None and sorted_field["bom_pct"] else None)
        price_pct = pct.get("price_pct")
        m["analysis"] = {
            "specs_typed": t,
            "percentiles": pct,
            "scores": compute_scores(t, stats, bom_pct, price_pct),
            "highlights": _highlights(t),
        }

    doc["analysis_stats"] = stats
    doc["analysis_disclaimer"] = (
        "Typed specs are parsed from each bike's published specifications. "
        "Percentiles and 0-100 scores are heuristic, field-relative comparison "
        "aids only -- there is no composite score; rank on whichever criteria matter."
    )
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()

    Path(args.input).write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    enriched = sum(1 for m in models if "analysis" in m)
    miss_price = sum(1 for m in models if m["analysis"]["scores"].get("value") is None)
    print(f"Wrote {Path(args.input).name}: analysis on {enriched}/{len(models)} models, "
          f"{len(stats)} field distributions ({miss_price} without a value score).")


if __name__ == "__main__":
    main()
