#!/usr/bin/env python3
"""
Build the analysis layer on top of the normalized e-bike dataset.

Reads `data/ebike.json` (and component prices from
`data/component_catalog.json` — researched or context-estimated per part), and for
every model derives:

  TIER 1 - `specs_typed`: predictable, unit-fixed, *searchable* fields parsed out
           of the free-text specs (battery_wh, torque_nm, range_mi, motor_w,
           weight_lb, warranty_years, brake_type, ...). One fixed type+unit per
           field across all models. Missing -> null (never coerced to 0).

  TIER 2 - value-added "how does it compare to the field" signals:
           `percentiles` (each numeric field's rank within the field, 0..1) and
           `scores` (transparent per-dimension 0-100). These are a quick compare
           aid only -- there is deliberately NO composite/overall score, so the
           site can rank purely on whichever criteria the user cares about.

The result is written back into `ebike.json` (an `analysis` block per
model, plus a top-level `analysis_stats` with the field distributions). The raw
per-brand files and the rest of the normalized doc are untouched.

Usage:  python analyze.py [-i data/ebike.json] [--catalog data/component_catalog.json]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from spec_parse import num, find_spec, blob, kg_to_lb, percentile_rank, height_range_in, is_mid_drive
from parse_components import bosch_torque
from spec_groups import flatten_grouped
from component_catalog import iter_components
from resolve_component_prices import heuristic_retail
from component_refs import rehydrate

HERE = Path(__file__).parent
DATA = HERE / "data"

# Numeric typed fields that get a field-relative percentile. `weight_lb` is
# inverted (lighter ranks higher); the rest are higher-is-better.
NUMERIC_FIELDS = [
    "battery_wh", "motor_w", "motor_peak_w", "torque_nm",
    "range_mi", "weight_lb", "gears", "max_speed_mph", "max_load_lb",
]
INVERTED = {"weight_lb"}

# Lightweight, small-battery bikes ride like fitness/hybrid bikes (more pedaling,
# less assist) even when nothing in the name says so — e.g. Ride1Up Roadster V3
# (40 lb / 360 Wh). They get tagged "Hybrid / Fitness" in addition to their other
# types. Both gates required so heavy or big-battery bikes never qualify.
HYBRID_FITNESS = "Hybrid / Fitness"
HYBRID_MAX_WEIGHT_LB = 46
HYBRID_MAX_BATTERY_WH = 420

WARRANTY_SCORE = {1: 20, 2: 45, 3: 65, 4: 80}   # >=5 or Lifetime -> 100


# ----------------------------- TIER 1: typed specs -----------------------------

def _battery_wh(specs):
    # "nominal_energy" covers brands whose battery rows never say "battery"
    # (Segway: "Nominal Energy: 722 Wh")
    txt = find_spec(specs, "battery", "cell", "nominal_energy", "nominal energy")
    wh = num(r"(\d{3,4}(?:\.\d+)?)\s*wh", txt)
    if wh is None:
        v = num(r"(\d{2,3}(?:\.\d+)?)\s*v\b", txt)
        ah = num(r"(\d{1,2}(?:\.\d+)?)\s*ah", txt)
        if ah and not v:
            # The pack voltage sometimes lives on the controller row instead
            # (Ride1Up Vorsa: battery "15Ah ...", controller "48V 25A ...").
            # Controller voltage is the pack's nominal voltage; the charger's
            # is the (higher) charge voltage, so it is deliberately not used.
            v = num(r"(\d{2,3}(?:\.\d+)?)\s*v\b", find_spec(specs, "controller"))
        if v and ah:
            wh = v * ah
    return round(wh) if wh else None


def _cell_brand(specs):
    txt = find_spec(specs, "battery", "cell").lower()
    for b in ("samsung", "lg", "panasonic", "molicel", "sony"):
        if b in txt:
            return b
    return "generic" if txt else None


# Nominal ratings for motors whose spec rows never state watts (the maker
# publishes torque only, e.g. Brose quotes the TF Sprinter at 250W nominal
# off-page). Curated facts, matched against the motor row text.
_KNOWN_MOTOR_W = [
    # match the model name alone: the component parser may reorder the row
    # ("Brose mid 90Nm TF Sprinter German made motor with")
    (re.compile(r"tf[\s-]*sprinter", re.I), 250),
    # every Bosch e-bike drive unit (Active/Performance/Cargo Line, CX, ...)
    # is 250W nominal; Bosch publishes torque, never watts
    (re.compile(r"\bbosch\b", re.I), 250),
    # Shimano EP/STePS drive units are likewise 250W nominal, torque-only specs.
    # EP model numbers (EP801...) match standalone: the flattened component may
    # reorder tokens away from "Shimano"; bare "shimano" would false-match
    # drivetrain rows (find_spec's "drive" keys include drivetrain).
    (re.compile(r"shimano\s*(?:ep\d|steps)|\bep[5-8]\d{2}\b", re.I), 250),
]


def _motor_w(specs):
    def dethousand(s):
        # "1,200W" must read 1200, not 200
        return re.sub(r"(?<=\d),(?=\d{3})", "", s)
    txt = dethousand(find_spec(specs, "motor", "drive", "hub"))
    # Some brands put the rating in the LABEL, not the value (Segway:
    # "Rated Power: 500W" / "Peak Power: 1500W" rows) — fold those rows into
    # the text with their qualifier re-attached so the parse below sees them.
    rated_row = dethousand(find_spec(specs, "rated_power", "rated power"))
    peak_row = dethousand(find_spec(specs, "peak_power", "peak power"))
    if rated_row:
        txt = f"{txt} {rated_row}"
    if peak_row:
        mw = re.search(r"(\d{3,4})\s*w\b", peak_row, re.I)
        if mw:
            txt = f"{txt} {mw.group(1)}W peak"
    if not txt.strip():
        return None, None
    # The boost wattage is the bike's true peak (highest shipped-mode output);
    # pull it before stripping the parenthetical so it can't read as continuous.
    bm = (re.search(r"(\d{3,4})\s*w(?:att)?s?[^)0-9]{0,12}boost", txt, re.I)
          or re.search(r"boost[^)0-9]{0,15}(\d{3,4})\s*w", txt, re.I))
    boost = float(bm.group(1)) if bm else None
    # vendor wording "NNNW Peak in BOOST" marks the boost figure as THE peak,
    # which demotes a "Peak"-labeled standard figure to nominal (see below)
    boost_is_peak = bool(re.search(r"\d\s*w(?:att)?s?\s*peak[^)0-9]{0,10}boost", txt, re.I))
    txt = re.sub(r"\([^)]*boost[^)]*\)", " ", txt, flags=re.I)
    # The motor rows reaching this point are flatten_grouped() renderings of the
    # parsed component ("1188W peak 750W 80Nm"), so the number-adjacent "NNNW
    # peak" form binds first; the "peak NNNW" form covers unparsed free text.
    # Pull peak, then strip every peak mention so none reads as continuous.
    # w(?:att)?s? : "350 watts (550w peak)" must read nominal 350 / peak 550.
    # (?!h)(?![\s-]*hours?) : "520Wh" / "601 watt-hours" are battery capacity.
    _W = r"w(?:att)?s?\b(?!h)(?![\s-]*hours?)"
    peak = (num(rf"(\d{{3,4}})\s*{_W}\s*peak", txt)
            or num(rf"peak[^0-9,()/]{{0,14}}(\d{{3,4}})\s*{_W}", txt)
            # "(900 Peak)" -- the W is sometimes dropped after the peak figure (Vanpowers)
            or num(r"(\d{3,4})\s*w?\s*peak", txt))
    cont_txt = re.sub(rf"\d{{3,4}}\s*{_W}\s*peak", " ", txt, flags=re.I)
    cont_txt = re.sub(rf"peak[^0-9,()/]{{0,14}}\d{{3,4}}\s*{_W}", " ", cont_txt, flags=re.I)
    cont_txt = re.sub(r"\d{3,4}\s*w?\s*peak", " ", cont_txt, flags=re.I)
    cont = num(rf"(\d{{3,4}})\s*{_W}", cont_txt)
    # With a boost figure present it is the true peak; when its wording says
    # "peak", the standard "Peak"-labeled figure is really the nominal.
    if boost:
        if boost_is_peak and peak and peak != boost and cont is None:
            cont = peak
        peak = max(boost, peak or 0)
    if cont is None:
        for rx, w in _KNOWN_MOTOR_W:
            if rx.search(txt):
                cont = w
                break
    return (round(cont) if cont else None), (round(peak) if peak else None)


def _torque_nm(specs):
    # torque is often quoted in a motor/hub/power row rather than a "torque" row
    # (e.g. hub_rear "…hub motor, 80Nm, 1400W" or power "550 peak watts, 45nm peak")
    txt = find_spec(specs, "torque", "motor", "hub", "drive", "power")
    nm = num(r"(\d{2,3})\s*n\W{0,2}m", txt)        # 80Nm | 105 N·m | 42nm
    if nm:
        return round(nm)
    # Bosch states torque per motor line, not in every row — fall back to the known value.
    return bosch_torque(txt)


_AWD_RE = re.compile(r"dual[\s-]?motor|all[\s-]?wheel[\s-]?drive|\bawd\b|two motors|\b2wd\b", re.I)


def _awd(model, specs):
    """All-wheel drive (two drive motors): true when the bike has both a front and
    a rear motor component, or any spec/name text states dual-motor/AWD."""
    has_front = has_rear = False
    for rows in (model.get("specs") or {}).values():
        for k, v in rows.items():
            if isinstance(v, dict) and v.get("_kind") == "motor":
                if k.startswith("front"):
                    has_front = True
                elif k.startswith("rear"):
                    has_rear = True
    if has_front and has_rear:
        return True
    return bool(_AWD_RE.search(f"{blob(specs)} {model.get('model') or ''}")) or None


def _drive_type(specs):
    txt = find_spec(specs, "motor", "drive").lower()
    if not txt:
        return None
    # \bmid\b: the parsed component's placement renders as the bare token "mid"
    # in the flattened text ("Brose mid 90Nm ..."); the lookahead keeps frame
    # wording like "mid-step" from false-matching. is_mid_drive() also recognizes
    # mid-drive motors named only by brand/model (Bosch CX, Shimano EP, etc.).
    if re.search(r"\bmid\b(?![\s-]?step)", txt) or is_mid_drive(txt):
        return "mid"
    return "hub"


def _range_vals(specs):
    txt = find_spec(specs, "range")
    vals = [float(g) for g in re.findall(r"(\d{2,3})\s*(?:mile|mi\b)", txt, re.I)]
    if not vals:                                   # bare numbers in a range row
        vals = [float(g) for g in re.findall(r"\b(\d{2,3})\b", txt)]
    return vals


def _range_mi(specs):
    vals = _range_vals(specs)
    return round(max(vals)) if vals else None


def _range_min_mi(specs):
    """Low end of a stated range span (e.g. "45-90 miles" -> 45); None when only a
    single figure is given, so the card can show "low/high" like motor W."""
    vals = _range_vals(specs)
    if len(vals) < 2:
        return None
    lo, hi = round(min(vals)), round(max(vals))
    return lo if lo != hi else None


def _weight_lb(specs):
    # Only the bike's own weight -- skip rider/payload/cargo/capacity rows, which
    # also quote pounds (e.g. "Recommended Rider Weight: <250lbs", "Weight Limit:
    # 450 lbs"). "gross" weight is bike + packaging/load, not the bike's own; the
    # bike's bare weight is "Net Weight" / "Curb Weight" / a plain "Weight".
    bad = ("rider", "payload", "cargo", "recommended", "capacity", "load", "max",
           "limit", "gross")
    rows = {k: v for k, v in specs.items()
            if "weight" in k.lower() and not any(b in k.lower() for b in bad)}
    txt = find_spec(rows, "weight")
    lb = num(r"(\d{2,3}(?:\.\d+)?)\s*lb", txt)
    if lb is not None:
        return round(lb, 1)
    kg = num(r"(\d{2,3}(?:\.\d+)?)\s*kg", txt)
    if kg:
        return kg_to_lb(kg)
    # "N.W/G.W" net/gross rows (CEMOTO: "27kg/132kg" = net 27 / gross 132): the
    # bike's own weight is the NET (first) figure; gross includes packaging.
    for k, v in specs.items():
        if re.search(r"n[._\s]*w.*g[._\s]*w|net[._\s]*weight", k, re.I):
            mm = re.match(r"\s*(\d{2,3}(?:\.\d+)?)\s*(lb|kg)?", str(v))
            if mm:
                val = float(mm.group(1))
                return round(val if (mm.group(2) or "").lower() == "lb" else kg_to_lb(val), 1)
    return None


# The BIKE's max payload and a REAR RACK's capacity are different max-weight specs
# (a bike's own payload is often unlisted; a rack's capacity should be), so keep
# them separate. Both appear under ~50 label variants.
_BIKE_LOAD_RE = re.compile(
    r"payload|load.?capac|weight.?limit|weight.?capac|carry.?capac"
    r"|max[\s_\w]{0,15}load"   # "max load", "max bike load", "maximum load"
    r"|(?:rider|system|total).*weight|gross.?vehicle.*weight|max.?rider.?weight", re.I)
# A rack row's label is usually just "rack"/"rear_rack" with the capacity in the
# value ("…, 100 lb capacity"), so match the label on "rack" alone — the lb/kg
# pull below supplies the number. (?<![bt]) keeps "bracket"/"track" out.
_RACK_LOAD_RE = re.compile(r"(?<![bt])rack", re.I)
# NOT the bike's payload: rack/basket sub-limits, the fork, or the bike's OWN
# (gross/curb/net/unladen) weight.
_LOAD_NOT_BIKE = ("rack", "basket", "fork", "gross_weight", "curb", "net_weight", "unladen")


def _lbs_from(specs, label_re, bad=()):
    """Largest lb figure across spec rows whose label matches `label_re` (and not
    `bad`); falls back to converting the largest kg figure."""
    lbs, kgs = [], []
    for k, v in specs.items():
        kl = k.lower()
        if not label_re.search(kl) or any(b in kl for b in bad):
            continue
        s = str(v)
        lbs += [float(x) for x in re.findall(r"(\d{2,4}(?:\.\d+)?)\s*lb", s, re.I)]
        kgs += [float(x) for x in re.findall(r"(\d{2,4}(?:\.\d+)?)\s*kg", s, re.I)]
    if lbs:
        return round(max(lbs))
    if kgs:
        return round(kg_to_lb(max(kgs)))
    return None


def _max_load_lb(specs):
    """The BIKE's max payload / total-weight limit (lb) -- not a rack/basket/own weight."""
    return _lbs_from(specs, _BIKE_LOAD_RE, _LOAD_NOT_BIKE)


def _rack_load_lb(specs):
    """Rear-rack max load capacity (lb)."""
    return _lbs_from(specs, _RACK_LOAD_RE)


# Brake make/model families that are exclusively hydraulic disc, used to type a
# brake whose spec text never spells out "hydraulic". Matched within brake-
# labelled text only, so brand words can't leak in from elsewhere.
_HYDRAULIC_MODEL = re.compile(
    r"\bhd[-\s]?[a-z]?\d"            # Tektro/Shimano part nos: HD-T5040, HD-M745
    r"|\bdb[68]\b"                   # SRAM DB6 / DB8
    r"|maven|trickstuff|magura|hayes|\bhope\b|formula"   # hydraulic-only brands
    r"|\bcode\b|\bguide\b|\blevel\b|\bg2\b"              # SRAM MTB hydraulic
    r"|br[-\s]?mt|bl[-\s]?mt|bl[-\s]?u"                  # Shimano hydraulic levers/calipers
    r"|deore|\bslx\b|\bxtr?\b|cues"                      # Shimano groups (hydraulic here)
    r"|dh[-\s]?r|orion"                                 # TRP DH-R, Tektro Orion
    r"|(?:force|rival|red|apex)\s*(?:e?tap\s*)?(?:axs|e1)|sram\s+red\b",  # SRAM road hydraulic
    re.I,
)


def _brake_type(specs):
    txt = find_spec(specs, "brake").lower()
    if not txt:
        return None
    # Genuine rim brakes are near-extinct on e-bikes, so only call it when the
    # text says so explicitly — never as a fallback for an unrecognized brake.
    # \b before v-brake so it can't match the "v brake" inside Shimano's "I-spec EV brake"
    # (the Giant Reign's 4-piston hydraulic disc was misread as a rim brake).
    if re.search(r"\brim brake|\bv[-\s]?brake|cantilever|linear[-\s]?pull|coaster", txt):
        return "rim"
    if "hydraulic" in txt:
        return "hydraulic_disc"
    if re.search(r"mechanical|cable", txt):
        return "mechanical_disc"
    # The word "hydraulic" is often missing, but the brake make/model gives it
    # away: these families/prefixes are hydraulic-only. (Checked after the
    # explicit mechanical/cable test so a stated mechanical brake still wins.)
    if _HYDRAULIC_MODEL.search(txt):
        return "hydraulic_disc"
    # disc when stated or implied by a disc-only feature (rotor mm / piston count)
    if re.search(r"\bdisc\b|\brotor\b|\d{3}\s*mm|piston", txt):
        return "disc"
    # a brake we couldn't type; on e-bikes that's overwhelmingly a disc brake
    return "disc"


def _drivetrain_type(specs):
    # include "belt" — some bikes put the drive medium in a row labelled "Belt"
    # ("Gates 115t CDX"), which the other keywords miss (e.g. Priority Skyline).
    txt = find_spec(specs, "belt", "derailleur", "cassette", "freewheel", "chain",
                    "drivetrain", "shift", "gear", "transmission").lower()
    if not txt:
        return None
    if re.search(r"belt|gates|carbon drive", txt):
        return "belt"
    if re.search(r"enviolo|cvt|nuvinci|internal gear|igh|auto[- ]?shift|pinion|gearbox"
                 r"|rohloff|nexus|alfine|hub gear", txt):
        return "internal_gear"
    if re.search(r"single[- ]?speed|singlespeed|\b1[- ]?speed", txt):
        return "single_speed"
    # "derailleur" only with real gearing evidence -- otherwise an incidental
    # match (e.g. the "chainstay" geometry row matching the "chain" keyword) would
    # wrongly assume a derailleur on a single-speed/belt bike.
    if re.search(r"derailleur|cassette|freewheel|sprocket|\bcog\b|shimano|sram"
                 r"|microshift|sunrace|l-?twoo|\d{1,2}\s*-?\s*(?:speed|spd)\b", txt):
        return "derailleur"
    return None


def _gears(specs):
    # flatten_grouped stringifies parsed components with speeds as "10-speed",
    # so this also catches derailleurs that never say "speed" in words.
    txt = blob(specs)
    sp = num(r"(\d{1,2})[- ]?speed", txt)
    return int(sp) if sp else None


def _shock_text(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(v.get(x) or "") for x in
                        ("manufacturer", "model", "type", "size", "details")).strip().lower()
    return str(v or "").strip().lower()


def _has_rear_shock(model: dict) -> bool:
    """A genuine rear shock / rear-suspension COMPONENT — the thing that actually makes a
    bike full-suspension (vs a front fork). A dedicated rear_shock/rear_suspension field is
    trusted; a generic "shock" field counts only when it names a real damper (a maker or an
    eye-to-eye size like 210x55), since scrapes miscategorise front forks, seatpost springs,
    and empty/"n/a" rows into a "shock" field. The bare 'full suspension' phrase is ignored."""
    for fields in (model.get("specs") or {}).values():
        if not isinstance(fields, dict):
            continue
        for k, v in fields.items():
            kl = k.lower()
            txt = _shock_text(v)
            if not txt or "n/a" in txt or txt == "none" or "fork" in txt or "front" in txt:
                continue   # placeholder, or a front fork miscategorised as a shock
            if re.search(r"rear[_\s-]?shock|rear[_\s-]?susp", kl):
                return True
            if kl == "shock" and ((isinstance(v, dict) and v.get("manufacturer"))
                                  or re.search(r"\d+\s*x\s*\d+", txt)):
                return True
    return False


def _suspension(specs, has_rear_shock=False):
    txt = find_spec(specs, "fork", "suspension").lower()
    if not txt and not has_rear_shock:
        return None
    # FULL suspension means a real REAR shock — a dedicated rear-shock component, or an
    # explicit rear/Horst/linkage/swingarm/dual signal. A bare "full suspension" detail is
    # a spec artifact (Cannondale tags it even on rigid-fork comfort bikes) and is NOT
    # sufficient on its own.
    if has_rear_shock or re.search(r"rear[- ]?(shock|spring|suspension|damper)|\bhorst\b"
                                   r"|\blinkage\b|swing\s?arm|dual[- ]?suspension", txt):
        return "full"
    # strip that artifact so its lone "suspension" word can't upgrade a rigid fork below
    txt = re.sub(r"full[\s-]?suspension", " ", txt)
    if re.search(r"\bair\b", txt):
        return "air_fork"
    if re.search(r"coil|spring|hydraulic|lock[- ]?out|suspension", txt):
        return "coil_fork"
    return "rigid"


def _frame_material(specs):
    txt = find_spec(specs, "frame").lower()
    if not txt:
        return None
    # "carbon" means carbon *fiber* ONLY. "carbon steel" / "high|low|mid|mild
    # carbon" are STEEL, and a "Gates Carbon Drive" belt is a DRIVETRAIN, not a
    # frame -- the lookbehinds drop the steel qualifiers and the lookahead drops
    # "carbon steel/drive/belt".
    if re.search(r"(?<!high )(?<!high-)(?<!low )(?<!low-)(?<!mid )(?<!mid-)"
                 r"(?<!medium )(?<!medium-)(?<!mild )(?<!mild-)"
                 r"carbon(?![\s-]*(?:steel|drive|belt))", txt):
        return "carbon"
    # A named aluminium alloy (6061/6063/7005; A356/A380 castings) or Giant's ALUXX
    # means the frame is aluminium even when the text also says "steel" (a mislabelled
    # casting or mixed front/rear) -- checked before steel AND before the composite rule
    # below, since Giant's aluminium frames carry an "Advanced Forged Composite" rocker.
    if re.search(r"alum|aluminium|aluxx|\balloy\b|6061|6063|7005"
                 r"|\ba3\d{2}\b|\ba380\b|\b\d{4}\s*-?\s*al\b|\bal[-\s]?\d{4}\b", txt):
        return "aluminum"
    # "composite" = carbon fibre when it's the frame's own material (Giant labels its
    # carbon frames "Advanced-grade composite" rather than "carbon"). Reaches here only
    # when no carbon/aluminium/alloy word matched, so it can't shadow an alloy frame.
    if "composite" in txt:
        return "carbon"
    # carbon steel / high-carbon / Q-grade steel / chromoly all land here as steel
    if re.search(r"carbon[\s-]*steel|(?:high|low|mid|medium|mild)[\s-]*carbon"
                 r"|\bq\d{3}\b|steel|cr-?mo|chromoly|\biron\b", txt):
        return "steel"
    return None


# ----------------------- e-bike class & top speed -----------------------
# Rows worth reading for class/speed signal. Key-gated so "8-speed derailleur",
# walk-mode speeds, and "best-in-class ... fork" marketing can't false-match.
_CLASS_KEY = re.compile(
    r"class|speed|ride.?mode|riding.?mode|classification|\bpas\b|pedal.?assist|motor|app", re.I)
_CLASS_KEY_NOT = re.compile(
    r"walk|suspension|fork|battery|charger|derailleur|shifter|cassette|drivetrain", re.I)
# "Class 2", "Class 1/2/3", "Class 1, 2, or 3", "CLASS & SPEED: 1-3", "Class 1
# (Convertible to Class 2 and/or Class 3)" -- every digit reachable from a
# "class" mention counts as a supported/configurable mode.
_CLASS_LIST = re.compile(
    r"class(?:es|ification)?[\s_]*(?:&[\s_]*speed)?[\s_:-]*"
    r"([123](?:(?:\s*(?:[/,&+]|or|and|to|-)\s*)+[123])*)", re.I)
_MPH = re.compile(r"(\d{2}(?:\.\d)?)\s*-?\s*(?:mph|miles?\s+per\s+hour)", re.I)
_KPH = re.compile(r"(\d{2}(?:\.\d)?)\s*-?\s*(?:kph|km/?h)", re.I)
_CUSTOM_MODE = re.compile(
    r"custom\s+(?:mode|riding|profile)|riding\s+profiles?[^.]*custom|adjustable\s+top\s+speed"
    r"|user\s+adjustable", re.I)


def _class_speed_rows(specs):
    return [f"{k} {v}" for k, v in specs.items()
            if _CLASS_KEY.search(k) and not _CLASS_KEY_NOT.search(k)]


def _classes(rows):
    """Supported e-bike classes ([1], [1,2,3], ...), incl. convertible modes."""
    out = set()
    for t in rows:
        for grp in _CLASS_LIST.findall(t):
            nums = [int(x) for x in re.findall(r"[123]", grp)]
            if "-" in grp and len(nums) == 2:  # "1-3" span form
                nums = list(range(nums[0], nums[1] + 1))
            out.update(nums)
    return sorted(out) or None


def _max_speed_mph(rows, classes):
    """Top assisted speed: the site's own figure wins (largest stated mph,
    converting kph-only rows); else the class-implied legal maximum
    (Class 3 -> 28 mph, Class 1/2 -> 20 mph)."""
    mph = [float(v) for t in rows for v in _MPH.findall(t) if 10 <= float(v) <= 60]
    if mph:
        return round(max(mph))
    kph = [float(v) for t in rows for v in _KPH.findall(t) if 16 <= float(v) <= 96]
    if kph:
        return round(max(kph) * 0.621371)
    if classes:
        return 28 if 3 in classes else 20
    return None


def _custom_speed_mode(rows):
    """True when the bike advertises a custom/user-adjustable speed mode."""
    return True if any(_CUSTOM_MODE.search(t) for t in rows) else None


def _sensor_type(specs):
    # read the sensor / pedal-assist / assist-type / bottom-bracket rows only -- NOT the
    # motor row's torque RATING ("Max Torque 80Nm"), which is not a torque SENSOR. A
    # "speed sensor" is the same thing as a cadence sensor. Bafang torque-sensing bottom
    # brackets and an "Assist Type: Cadence/Torque" row both name the real sensor.
    txt = find_spec(specs, "sensor", "pedal", "assist", "bottom").lower()
    # ...but a motor explicitly described as "torque sensing" / "cadence sensing"
    # DOES name a real sensor (Priority: "torque sensing motor"). Fold that in,
    # matching only the SENSOR phrasing (…sens…) so a bare "140 Nm" rating can't.
    motor_txt = find_spec(specs, "motor", "drive").lower()
    # Giant's SyncDrive / PedalPlus multi-sensor system is torque-sensing (it measures
    # rider torque, pedalling cadence, and wheel speed) -- name it torque + cadence.
    giant = bool(re.search(r"pedalplus|pedal\s*plus|syncdrive", motor_txt))
    has_t = "torque" in txt or bool(re.search(r"torque[\s-]*sens", motor_txt)) or giant
    has_c = ("cadence" in txt or bool(re.search(r"speed[\s-]?sensor", txt))
             or bool(re.search(r"cadence[\s-]*sens", motor_txt)) or giant)
    if has_t and has_c:
        return "torque + cadence"
    if has_t:
        return "torque"
    if has_c:
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
    # safety certification: UL 2849/2271/2580 (US) or the equivalent EN 15194 (EU,
    # e.g. Tern). Surfaced as one "UL / EN certified" filter.
    return True if re.search(r"ul\s*-?\s*(2271|2849|2580)|en\s*-?\s*15194",
                             blob(specs), re.I) else None


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
        # NB: dual-battery is handled separately below — it must SHIP as standard, so it's
        # read from the battery spec (not the blob, where range text like "100 mi with
        # optional second battery" would falsely trip it).
        # Find My network integration (Apple Find My / iOS Find My, Google Find My
        # Device / Find Hub) and brand "find my bike" locators -- a locate/anti-theft
        # security feature; checked on every model.
        (r"apple find\s*my|ios find\s*my|google'?s? find|find hub|find my device"
         r"|find my bike|\bfindmy\b", "find my"),
        # anti-theft / tracking, incl. custom solutions (4G/GPS trackers, GPS/GSM
        # connect modules, geo-fence/electronic fence, motion alarm, immobilizer).
        (r"anti[- ]?theft|gps[\s/]?track|gps[\s/]?gsm|4g[\s/]?gps|electronic fence"
         r"|geo[- ]?fenc|movement alarm|motion alarm|immobili[sz]|\btracker\b"
         r"|connect module|\balarm\b", "anti-theft"),
        (r"fingerprint", "fingerprint unlock"),
        (r"torque sensor", "torque sensor"),
        (r"mid[- ]?drive", "mid-drive motor"),
        # uncommon premium kit
        (r"dropper", "dropper post"),
        (r"quad[- ]?piston|four[- ]?piston|4[- ]?piston", "4-piston brakes"),
        (r"\bdi2\b|\baxs\b|electronic shift", "electronic shifting"),
        (r"deore xt|\bxtr\b|\bslx\b|\bx01\b|\bxx1\b|gx eagle", "high-end drivetrain"),
        (r"enviolo|nuvinci|internal[- ]?gear|\bigh\b", "internal gear hub"),
        (r"can[\s-]?bus", "CANbus system"),
    ]
    for pat, label in checks:
        if re.search(pat, b):
            out.append(label)
    # Dual-battery counts ONLY when the bike ships with two packs as standard — read the
    # battery spec, the authoritative statement of what's included ("(2) ... batteries",
    # "Two removable ... batteries", "2x battery", "dual battery"). A second pack offered
    # as an optional add-on / upgrade is NOT default, so it isn't a feature.
    batt = find_spec(specs, "battery").lower()
    ships_dual = re.search(
        r"\bdual[- ]?batter|\(2\)[^.;]*batter|\b2\s*x\s*batter|\b2\s+removable\b"
        r"|\btwo\s+(?:removable\s+)?[^.;]*?batter", batt)
    # ...nor when the spec only says the bike is dual-CAPABLE: "Bosch Dual Battery pack
    # ready", "dual-battery compatible/expandable" ship with one pack.
    optional_dual = re.search(
        r"optional|add[- ]?on|upgrade|sold separately|available separately"
        r"|\bready\b|compatible|capable|expandable", batt)
    if ships_dual and not optional_dual:
        out.append("dual-battery")
    return out


_KIDS_RE = re.compile(r"\b(kids?|youth|junior|children'?s?)\b", re.I)


def _kids(model: dict) -> bool | None:
    """True for a kids-only model. Keyed off the model name (the reliable signal,
    e.g. "Himiway C1 Kids eBike"); a broad spec scan false-matches "child seat",
    payload "age" substrings, etc."""
    return True if _KIDS_RE.search(model.get("model") or "") else None


_FRAME_LBL = r"high[\s-]?step|step[\s-]?thr(?:u|ough)|step[\s-]?over|mid[\s-]?step"


def _height_for_frame(value, frame_style):
    """When a rider-height string bundles a range per frame style (Monarc:
    "High-Step: 5'4"-6'5" Step-Thru: 5'2"-6'3""), return only the segment matching
    this model's frame style; otherwise return the value unchanged (so a single
    range or per-size dict is enveloped as before)."""
    if not isinstance(value, str):
        return value
    pairs = re.findall(rf"({_FRAME_LBL})\s*:?\s*(.*?)(?=(?:{_FRAME_LBL})|$)",
                       value, re.I | re.S)
    if not pairs:
        return value
    thru = bool(re.search(r"thr(?:u|ough)", frame_style or "", re.I))
    for label, body in pairs:
        if bool(re.search(r"thr(?:u|ough)", label, re.I)) == thru:
            return body
    return value


def _is_rider_height_key(kl: str) -> bool:
    """A key that names a RIDER-FIT height — not a geometry height (standover /
    head-tube / stack / seat). Beyond "rider height", accept brand phrasings like
    "Approx. Height" / "Approx. Inseam and Height" (Priority), "Recommended/Suggested
    Height", "Fits Riders". Safe to be liberal: height_range_in only yields a range
    from feet-inch values, so inseam inches and mm geometry never false-match."""
    return "height" in kl and any(
        q in kl for q in ("rider", "recommended", "suggested", "approx", "fit"))


def _fit_height(model: dict) -> tuple[float | None, float | None]:
    """(min_in, max_in) the bike can fit, enveloped across every published
    rider-height range and frame size, or (None, None) -- unrounded inches, so the
    caller can derive precise mm bounds for the metric search. Reads the GROUPED
    geometry (model.specs.geometry) where a per-size dict is preserved -- the
    flattened specs would stringify it -- so "any frame size that fits" is captured."""
    geo = (model.get("specs") or {}).get("geometry") or {}
    lo = hi = None
    for k, v in geo.items():
        if _is_rider_height_key(k.lower()):
            r = height_range_in(_height_for_frame(v, model.get("frame_style")))
            if r:
                lo = r[0] if lo is None else min(lo, r[0])
                hi = r[1] if hi is None else max(hi, r[1])
    # A rider-height row can also land outside the geometry group (some brands list
    # "Recommended Rider Height" among general specs), so scan every other group's
    # string values too.
    for group, rows in (model.get("specs") or {}).items():
        if group == "geometry":
            continue
        for k, v in (rows or {}).items():
            if _is_rider_height_key(k.lower()) and isinstance(v, str):
                r = height_range_in(_height_for_frame(v, model.get("frame_style")))
                if r:
                    lo = r[0] if lo is None else min(lo, r[0])
                    hi = r[1] if hi is None else max(hi, r[1])
    # Also envelope across per-frame-size heights when frame_sizes carries them.
    # Some size charts list a rider range per frame only (e.g. a size-guide image
    # captured into a curated override), with no geometry rider_height_range.
    for fs in model.get("frame_sizes") or []:
        lo_s, hi_s = fs.get("height_min"), fs.get("height_max")
        if lo_s and hi_s:
            r = height_range_in(f"{lo_s} - {hi_s}")
            if r:
                lo = r[0] if lo is None else min(lo, r[0])
                hi = r[1] if hi is None else max(hi, r[1])
    return (lo, hi) if lo is not None else (None, None)


# Whole-page HTML extractions (resolve_missing_fields.py): fallback values for
# typed fields the spec sheet doesn't yield, with provenance (snippet + URL) in
# the curated file. Applied ONLY when the parsed value is absent.
try:
    HTML_EXTRACTED = json.loads(
        (Path(__file__).parent / "data" / "curated" / "html_extracted.json").read_text())
except (FileNotFoundError, ValueError):
    HTML_EXTRACTED = {}


def _listed_frame_size(specs):
    """A single stated frame-size label (e.g. '18\"') from a 'Frame Size' row -- not
    a wheel/tire size, not a chart header. None when the bike doesn't name one."""
    for k, v in specs.items():
        kl = k.lower()
        if "frame" in kl and "size" in kl and isinstance(v, str):
            val = v.replace("''", '"').strip()
            if val and len(val) <= 12 and not re.search(r"rider|height|inseam", val, re.I):
                return val
    return None


def _ensure_frame_sizes(model: dict, typed: dict) -> list:
    """frame_sizes is always a non-empty array. Multi-size bikes already carry one
    (from the size-chart enrichment); a single-size bike becomes a collection of
    one holding its rider-height range and listed frame size (if any). Heights come
    from the already-computed (frame-style-correct) fit envelope; null when the
    range couldn't be parsed."""
    fmt = lambda i: f"{int(i) // 12}'{int(i) % 12}\"" if i is not None else None
    fs = model.get("frame_sizes")
    if fs:
        # Backfill any null per-size rider heights from a per-size rider-height
        # geometry row keyed by the same size labels (e.g. Priority Glide:
        # rider_height = {"Small/Medium": "5'2\"-5'10\"", "Medium/Large": …}).
        geo = (model.get("specs") or {}).get("geometry") or {}
        per_size = next((v for k, v in geo.items()
                         if _is_rider_height_key(k.lower()) and isinstance(v, dict)), None)
        if per_size:
            by_lc = {str(k).lower(): v for k, v in per_size.items()}
            for e in fs:
                if e.get("height_min") or e.get("height_max"):
                    continue
                raw = by_lc.get(str(e.get("size")).lower())
                r = height_range_in(raw) if raw else None
                if r:
                    e["height_min"], e["height_max"] = fmt(r[0]), fmt(r[1])
        return fs
    lo, hi = typed.get("fit_height_min_in"), typed.get("fit_height_max_in")
    return [{"size": _listed_frame_size(flatten_grouped(model.get("specs") or {})),
             "height_min": fmt(lo), "height_max": fmt(hi)}]


def extract_typed_specs(model: dict) -> dict:
    # `specs` is the grouped map (group -> {field: value|parsed component});
    # flatten it back to a flat label->text map for the typed-fact regexes.
    specs = flatten_grouped(model.get("specs") or {})
    motor_w, motor_peak_w = _motor_w(specs)
    # Fit envelope emitted in BOTH inches and millimetres so the search can run in
    # the active unit (whole inches for imperial, mm for metric) without lossy
    # cross-unit rounding at query time.
    fit_lo_in, fit_hi_in = _fit_height(model)
    fit_min_in = round(fit_lo_in) if fit_lo_in is not None else None
    fit_max_in = round(fit_hi_in) if fit_hi_in is not None else None
    fit_min_mm = round(fit_lo_in * 25.4) if fit_lo_in is not None else None
    fit_max_mm = round(fit_hi_in * 25.4) if fit_hi_in is not None else None
    class_rows = _class_speed_rows(specs)
    bike_classes = _classes(class_rows)
    typed = {
        "battery_wh": _battery_wh(specs),
        "cell_brand": _cell_brand(specs),
        "removable_battery": True if re.search(r"removable", find_spec(specs, "battery"), re.I) else None,
        "motor_w": motor_w,
        "motor_peak_w": motor_peak_w,
        "torque_nm": _torque_nm(specs),
        "drive_type": _drive_type(specs),
        "awd": _awd(model, specs),
        "range_mi": _range_mi(specs),
        "range_min_mi": _range_min_mi(specs),
        "weight_lb": _weight_lb(specs),
        "max_load_lb": _max_load_lb(specs),
        "rack_load_lb": _rack_load_lb(specs),
        "brake_type": _brake_type(specs),
        "drivetrain_type": _drivetrain_type(specs),
        "gears": _gears(specs),
        "suspension": _suspension(specs, _has_rear_shock(model)),
        "frame_material": _frame_material(specs),
        "sensor_type": _sensor_type(specs),
        "classes": bike_classes,
        "max_speed_mph": _max_speed_mph(class_rows, bike_classes),
        "custom_speed_mode": _custom_speed_mode(class_rows),
        "display_type": _display_type(specs),
        "water_resistance": _water_resistance(specs),
        "ul_listed": _ul_listed(specs),
        "warranty_years": _warranty_years(model),
        "connectivity": _connectivity(specs),
        "notable_tech": _notable_tech(specs),
        "kids": _kids(model),
        # rider-height fit envelope for the "fits my height" filter, in both units
        "fit_height_min_in": fit_min_in,
        "fit_height_max_in": fit_max_in,
        "fit_height_min_mm": fit_min_mm,
        "fit_height_max_mm": fit_max_mm,
    }
    # html-extracted fallbacks: fill only absent fields; tag the model for
    # transparency (mirrors curated_overrides). A frame/tier sibling (its own id has
    # no entry) inherits the family base's extraction — the resolver ran on the base
    # scrape, but the bike-wide mechanicals (motor/brakes/belt/…) apply to every split.
    ext = (HTML_EXTRACTED.get(model.get("id"))
           or HTML_EXTRACTED.get(model.get("family_id"))
           or {})
    applied = []
    for f, e in ext.items():
        if typed.get(f) in (None, "", []):
            typed[f] = e.get("value")
            applied.append(f)
    if applied:
        model["html_extracted"] = sorted(applied)
    # Mid-drive systems (Bosch, Shimano, Brose, Yamaha, Specialized, TQ, …) are
    # torque-sensor based by design. When a brand never names the sensor in its specs,
    # infer torque from the mid-drive motor rather than leaving it blank — otherwise the
    # card's unknown-sensor fallback reads as an ambiguous cadence+torque glyph.
    if typed.get("sensor_type") is None and typed.get("drive_type") == "mid":
        typed["sensor_type"] = "torque"
    # Conversely, a HUB-drive bike that never names its sensor is overwhelmingly cadence-
    # based (a torque sensor on a hub motor is a premium exception that's always called
    # out), so default an unstated hub sensor to cadence. Uses the authoritative final
    # drive_type (set above), so hub bikes whose placement was resolved late are covered.
    elif typed.get("sensor_type") is None and typed.get("drive_type") == "hub":
        typed["sensor_type"] = "cadence"
    # The parsed drivetrain_type is authoritative: a belt / internal-gear bike HAS that
    # feature even when the spec table never spells out "belt"/"Gates" in scannable text
    # (e.g. Priority E-Coast / Vvolt, where it only survives as the drivetrain_type).
    nt = list(typed.get("notable_tech") or [])
    if typed.get("drivetrain_type") == "belt" and "belt drive" not in nt:
        nt.append("belt drive")
    if typed.get("drivetrain_type") == "internal_gear" and "internal gear hub" not in nt:
        nt.append("internal gear hub")
    typed["notable_tech"] = nt
    # an html-extracted rider-height (inches) implies the mm bounds too
    if typed.get("fit_height_min_in") and not typed.get("fit_height_min_mm"):
        typed["fit_height_min_mm"] = round(typed["fit_height_min_in"] * 25.4)
    if typed.get("fit_height_max_in") and not typed.get("fit_height_max_mm"):
        typed["fit_height_max_mm"] = round(typed["fit_height_max_in"] * 25.4)
    return typed


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
    fields = NUMERIC_FIELDS + ["price", "bom_pct", "value_ratio",
                               "component_retail_value_usd"]
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


def compute_scores(pct: dict, price_pct, value_rank, feature_score) -> dict:
    """The per-bike score block — every dimension is COHORT-relative (ranked within
    the bike's primary-type peers), so a $2k commuter isn't measured against a $12k
    eMTB. Independent 0-100 aids, never summed: there is no overall score.

      power/torque/range/battery -- cohort rank percentile of the magnitude
      price                      -- cohort affordability (cheaper ranks higher; price_pct pre-inverted)
      value                      -- cohort rank of price/parts-cost, inverted (best value highest)
      feature                    -- rarity-weighted equipment breadth vs peers (see feature_score)
    """
    s = {}

    def _rank(field):
        p = pct.get(f"{field}_pct")
        return round(p * 100, 1) if p is not None else None
    s["power"] = _rank("motor_w")
    s["torque"] = _rank("torque_nm")
    s["range"] = _rank("range_mi")
    s["battery"] = _rank("battery_wh")
    # weight: lighter ranks higher. weight_lb_pct is ALREADY inverted in
    # compute_percentiles (weight_lb is in INVERTED, like price), so use it directly —
    # a second (1 - wp) here would double-invert it back to heavier-is-higher.
    wp = pct.get("weight_lb_pct")
    s["weight"] = round(wp * 100, 1) if wp is not None else None
    s["price"] = round(price_pct * 100, 1) if price_pct is not None else None
    s["value"] = round((1 - value_rank) * 100, 1) if value_rank is not None else None
    # NB: the "feature" score was removed (too many bikes read low) — uncommon equipment
    # is now surfaced as the Uncommon Features list (analysis.uncommon_features) instead.
    return s


# --- Feature score: rarity-weighted breadth of equipment/tech/accessories ---------
# A bike's binary feature flags (present/absent). The Feature score rewards BREADTH
# and, via the per-cohort IDF weighting in main(), DISTINCTIVENESS -- a feature few
# same-type peers have is worth more than one they all share. Accessory flags only
# count when bundled free ($0); paid add-ons don't.
_ACC_FLAGS = [
    ("rack", re.compile(r"rack", re.I)),
    ("fenders", re.compile(r"fender", re.I)),
    ("lights", re.compile(r"light|headlight", re.I)),
    ("turn signals", re.compile(r"turn\s*signal", re.I)),
    ("basket", re.compile(r"basket", re.I)),
    ("phone mount", re.compile(r"phone\s*mount", re.I)),
]


def feature_flags(typed: dict, model: dict) -> set:
    """The set of binary features a bike has, drawn from typed specs + bundled
    accessories. Used to compute the per-cohort Feature score."""
    f = set()
    if typed.get("brake_type") == "hydraulic_disc":
        f.add("hydraulic brakes")
    if typed.get("suspension") in ("full", "air_fork"):
        f.add("suspension")
    if typed.get("sensor_type") in ("torque", "torque + cadence"):
        f.add("torque sensor")
    if typed.get("display_type") == "color_tft":
        f.add("color display")
    if typed.get("ul_listed"):
        f.add("UL listed")
    if typed.get("water_resistance"):
        f.add("water resistant")
    if model.get("folding"):
        f.add("folds")
    conn = typed.get("connectivity") or []
    for c in ("gps", "app", "alarm"):
        if c in conn:
            f.add(c)
    nt = typed.get("notable_tech") or []
    for k in ("ABS", "regen braking", "anti-theft", "find my", "fingerprint unlock",
              "belt drive", "dual-battery"):
        if k in nt:
            f.add(k)
    for acc in (model.get("included_accessories") or []):
        name = acc.get("name") if isinstance(acc, dict) else acc
        price = acc.get("price") if isinstance(acc, dict) else 0
        if not name or (price or 0) > 0:   # only truly-bundled ($0) gear
            continue
        for flag, rx in _ACC_FLAGS:
            if rx.search(str(name)):
                f.add(flag)
                break
    return f


# ----------------------------- standout features -----------------------------
# Equipment/tech worth flagging as a STANDOUT when it's uncommon in the bike's type
# cohort (prevalence < _STANDOUT_RARE). Broader than feature_flags (which feeds the
# Feature score) so it can surface premium kit the score doesn't weigh — kept separate
# so scoring is unchanged. Maps an internal token -> the badge label.
_STANDOUT_FEATURE_LABELS = {
    "dual-battery": "Dual Battery",
    "4-piston brakes": "4-Piston Brakes",
    "regen braking": "Regen Braking",
    "ABS": "ABS",
    "find my": "Find My",
    "anti-theft": "Anti-Theft",
    "fingerprint unlock": "Fingerprint Unlock",
    "belt drive": "Belt Drive",
    "dropper post": "Dropper Post",
    "electronic shifting": "Electronic Shifting",
    "internal gear hub": "Internal Gear Hub",
    "high-end drivetrain": "High-End Drivetrain",
    "color display": "Color Display",
    "carbon frame": "Carbon Frame",
    "full suspension": "Full Suspension",
    "torque sensor": "Torque Sensor",
    "water resistant": "Water Resistant",
    "UL listed": "UL / EN Certified",
    "CANbus system": "CANbus",
}
# Magnitude standouts: typed field -> (label, unit, round). weight is INVERTED upstream
# (lighter ranks higher), so a high weight_lb_pct == light. Motor handled separately
# (peak preferred). The cohort top-quartile gate (pct >= 0.75) is applied at call time.
_STANDOUT_MAG = {
    "range_mi": ("Long Range", "mi"),
    "torque_nm": ("High Torque", "Nm"),
    "battery_wh": ("Battery Size", "Wh"),
    "weight_lb": ("Lightweight", "lb"),
    "max_speed_mph": ("Top Speed", "mph"),
    "max_load_lb": ("Payload", "lb"),
}
_STANDOUT_TOP = 0.75      # top quartile of the cohort
_STANDOUT_RARE = 0.25     # equipment on < 25% of cohort peers
# Absolute "exceptional fleet-wide" gates (≈ fleet p90, round numbers): a magnitude spec
# badges when it clears these EVEN IF mid-pack in its cohort -- so a 3200 W eMoto motor
# shows even though its eMoto peers reach 8000 W. weight is "<=" (lighter is better).
_STANDOUT_ABS = {
    "torque_nm": 130, "range_mi": 110, "battery_wh": 1000,
    "max_speed_mph": 35, "max_load_lb": 450, "weight_lb": 45,
}
_STANDOUT_ABS_MOTOR_W = 1000        # nominal
_STANDOUT_ABS_MOTOR_PEAK_W = 2500   # peak

# Premium component recognition: absolute quality markers, named with the actual part.
# Matched against iter_components() make/model (or typed/spec text). Case-insensitive.
_PREM_BRAKE = re.compile(
    r"magura|\bxtr?\b|deore xt|\bslx\b|\bdeore\b|sram\s*(code|guide|level|db8)"
    r"|\btrp\b|\bhope\b|\bhayes\b|formula|tektro\s*(orion|hd-?e[4-9])", re.I)
_PREM_SUSP = re.compile(
    r"\bfox\b|rock\s*shox|marzocchi|öhlins|ohlins|\bdvo\b|dt\s*swiss"
    r"|suntour\s*(axon|durolux|rux)", re.I)
_PREM_CELL = {"samsung": "Samsung", "lg": "LG", "panasonic": "Panasonic"}
# premium sealed gearbox, named with its model (e.g. "Pinion C1.12i", "Rohloff E-14")
_PREM_GEARBOX = re.compile(r"\b(?:pinion|rohloff)(?:\s+[\w.\-]+)?", re.I)
_PREM_TIRE = {"maxxis", "schwalbe", "continental", "vittoria", "pirelli"}
_PREM_MOTOR = {"bosch", "brose", "specialized", "tq", "shimano", "yamaha", "mahle", "fazua"}
# carbon (fibre) in a fork spec -- reuses the frame regex's steel/drive/belt exclusions
_CARBON_FORK = re.compile(
    r"(?<!high )(?<!high-)(?<!low )(?<!low-)(?<!mid )(?<!mid-)(?<!medium )(?<!medium-)"
    r"(?<!mild )(?<!mild-)carbon(?![\s-]*(?:steel|drive|belt))", re.I)


def _part_name(part: dict) -> str:
    """Trimmed 'Make Model' for a parsed component (model optional)."""
    mk = (part.get("manufacturer") or "").strip()
    md = (part.get("model") or "").strip()
    return f"{mk} {md}".strip() if md else mk


def component_highlights(model: dict, typed: dict) -> list:
    """Premium/higher-quality components present on a bike, as {label, value} pairs with
    the actual part named (e.g. {"Brakes": "Magura MT4"}). ABSOLUTE quality markers --
    shown whenever present, independent of the cohort. One entry per label (first match)."""
    out, seen = [], set()

    def add(label, value):
        if label not in seen and value:
            seen.add(label)
            out.append({"label": label, "value": value})

    for _key, cat, part in iter_components(model):
        nm = _part_name(part)
        if cat == "brakes" and _PREM_BRAKE.search(nm):
            add("Brakes", nm)
        elif cat in ("fork", "shock", "rear_shock", "suspension") and _PREM_SUSP.search(nm):
            add("Fork", nm)
        elif cat == "tire" and (part.get("manufacturer") or "").lower() in _PREM_TIRE:
            add("Tires", (part.get("manufacturer") or "").strip())
        elif cat == "motor" and (part.get("manufacturer") or "").lower() in _PREM_MOTOR:
            add("Motor", _part_name(part))
    flat = flatten_grouped(model.get("specs") or {})
    # carbon fork from the fork spec text (only if no branded suspension already won)
    if "Fork" not in seen:
        if _CARBON_FORK.search(find_spec(flat, "fork")):
            add("Fork", "Carbon")
    # premium sealed gearbox -- Pinion / Rohloff are a distinctive, named drivetrain
    # (the Skyline's Pinion Smart.Shift), worth naming rather than a generic "IGH".
    gm = _PREM_GEARBOX.search(find_spec(flat, "drivetrain", "gear", "shift", "transmission", "cassette"))
    if gm:
        add("Gearbox", gm.group(0).strip())
    cell = _PREM_CELL.get((typed.get("cell_brand") or "").lower())
    if cell:
        add("Cells", cell)
    return out


def standout_features(typed: dict, model: dict) -> set:
    """Premium/uncommon equipment present on a bike (the universe rarity is judged
    against). Superset of the score's feature_flags, drawn from typed specs + notable_tech."""
    f = set()
    if typed.get("frame_material") == "carbon":
        f.add("carbon frame")
    if typed.get("suspension") == "full":
        f.add("full suspension")
    if typed.get("sensor_type") in ("torque", "torque + cadence"):
        f.add("torque sensor")
    if typed.get("display_type") == "color_tft":
        f.add("color display")
    if typed.get("ul_listed"):
        f.add("UL listed")
    if typed.get("water_resistance"):
        f.add("water resistant")
    for nt in typed.get("notable_tech") or []:
        if nt in _STANDOUT_FEATURE_LABELS:
            f.add(nt)
    return f


def standouts(pct: dict, typed: dict, st_flags: set, st_prev: dict, model: dict) -> list:
    """What makes a bike stand out, as {label, value} pairs (the UI renders one per line).
    Three groups, in order: (1) magnitude specs -- COHORT top-quartile OR an ABSOLUTE
    fleet-wide gate (so a huge motor shows even if its eMoto peers are bigger), value = the
    figure; (2) premium/named components (absolute quality markers); (3) equipment uncommon
    in the cohort (rarest first, no value). Capped."""
    mag = []  # (pct, label, value)
    # motor: prefer peak watts when present; qualify on cohort OR absolute nominal/peak gate
    mw_pct = max((pct.get("motor_w_pct") or 0), (pct.get("motor_peak_w_pct") or 0))
    mw = typed.get("motor_peak_w") or typed.get("motor_w")
    motor_abs = ((typed.get("motor_w") or 0) >= _STANDOUT_ABS_MOTOR_W
                 or (typed.get("motor_peak_w") or 0) >= _STANDOUT_ABS_MOTOR_PEAK_W)
    if mw and (mw_pct >= _STANDOUT_TOP or motor_abs):
        mag.append((mw_pct, "Motor Power", f"{mw} W"))
    for field, (label, unit) in _STANDOUT_MAG.items():
        p = pct.get(f"{field}_pct")
        v = typed.get(field)
        if v is None:
            continue
        gate = _STANDOUT_ABS.get(field)
        abs_ok = gate is not None and (v <= gate if field == "weight_lb" else v >= gate)
        if (p is not None and p >= _STANDOUT_TOP) or abs_ok:
            v = round(v) if isinstance(v, float) and v == int(v) else v
            mag.append((p if p is not None else 0, label, f"{v} {unit}"))
    mag.sort(key=lambda x: -x[0])

    rare = sorted((fl for fl in st_flags if st_prev.get(fl, 1.0) < _STANDOUT_RARE),
                  key=lambda fl: st_prev.get(fl, 1.0))
    out = [{"label": lbl, "value": val} for _, lbl, val in mag]
    out += component_highlights(model, typed)
    # folding is an absolute, distinctive feature -- highlight it whenever the bike folds
    if model.get("folding"):
        out.append({"label": "Folding", "value": ""})
    out += [{"label": _STANDOUT_FEATURE_LABELS[fl], "value": ""} for fl in rare]
    return out[:8]


# A value_ratio is only meaningful when the cost-dominant systems are accounted
# for; below this the small-denominator artifact would read as false "bad value".
_VALUE_MIN_PARTS = 5
_VALUE_CORE = {"battery", "motor"}


def _avg_cost(entry: dict):
    """The part's brand/spec-aware heuristic RETAIL estimate; None if its category
    has no estimator."""
    return heuristic_retail(entry)[0]


def component_quality(model: dict, catalog_entries: dict, price, typed: dict) -> dict:
    """Join the component catalog back onto one bike. Reports part counts, the
    aftermarket RETAIL roll-up, and a COMPLETE component base = sum over the bike's
    parts of each part's retail cost (researched where known, brand/spec heuristic
    otherwise). The dominant systems (battery, motor, frame) are costed from the
    bike's typed specs when no branded part was parsed, so the base isn't skewed by
    missing brands. `value_ratio` = price / base (lower = more parts per dollar =
    better value); gated to bikes with the core systems costed. Retail-only — wholesale
    was dropped (too hard to estimate). Facts only — never blended."""
    identified = priced = researched = retail_n = costed = 0
    retail_total = base_total = 0.0
    cats_costed = set()
    # Every line that contributes to component_base_value_usd, so the UI can show ALL
    # costs (parsed parts + the typed-spec system estimates) summing to the base — no
    # invisible fallbacks. {kind, label, cost, method: researched|estimate|spec_estimate}.
    base_breakdown = []
    for key, cat, part in iter_components(model):
        identified += 1
        e = catalog_entries.get(key) or {"category": cat, "attributes": part}
        am = e.get("aftermarket") or {}
        # a bike that SHIPS with multiple packs (Monarc dual-battery) is worth that many
        # batteries — the catalog price is per pack, so multiply by pack_count.
        pc = part.get("pack_count") if cat == "battery" else None
        qty = pc if isinstance(pc, int) and pc > 1 else 1
        r = am.get("retail_usd")
        if r is not None:
            retail_n += 1
            retail_total += r * qty
            priced += 1
        # the catalog now prices every part (researched or estimated); track how many
        # are a real lookup vs an estimate so the actual-vs-estimate split stays visible.
        if am.get("retail_method") == "researched":
            researched += 1
        # complete per-part base: researched retail where known, else the heuristic
        rp = r if r is not None else heuristic_retail(e)[0]
        if rp is not None:
            base_total += rp * qty
            costed += 1
            cats_costed.add(cat)
            label = " ".join(x for x in (part.get("manufacturer"), part.get("model")) if x) or cat
            base_breakdown.append({
                "kind": cat, "label": label + (f" ×{qty}" if qty > 1 else ""),
                "cost": round(rp * qty, 2),
                "method": "researched" if r is not None else "estimate"})
    # Cost the big-ticket systems from typed specs when no branded part was parsed
    # (most generic batteries/motors carry no manufacturer -> absent from iter_components).
    if "battery" not in cats_costed and typed.get("battery_wh"):
        # honor multi-pack systems (Monarc dual-battery): the bike ships with N packs,
        # so it's worth N× a single pack — read pack_count off the parsed battery.
        packs = 1
        for _fields in (model.get("specs") or {}).values():
            if isinstance(_fields, dict):
                for _v in _fields.values():
                    if isinstance(_v, dict) and _v.get("_kind") == "battery":
                        _pc = _v.get("pack_count")
                        if isinstance(_pc, int) and _pc > 1:
                            packs = max(packs, _pc)
        b, note = heuristic_retail({"category": "battery",
                       "attributes": {"capacity_wh": typed["battery_wh"] * packs,
                                      "cell_brand": typed.get("cell_brand")}})
        if b:
            base_total += b; costed += 1; cats_costed.add("battery")
            base_breakdown.append({"kind": "battery", "label": note or f"{typed['battery_wh']*packs} Wh battery",
                                   "cost": b, "method": "spec_estimate"})
    if "motor" not in cats_costed and typed.get("motor_w"):
        place = "mid" if typed.get("drive_type") == "mid" else "hub"
        b, note = heuristic_retail({"category": "motor",
                       "attributes": {"power_w": typed["motor_w"], "placement": place,
                                      "torque_nm": typed.get("torque_nm")}})
        if b:
            base_total += b; costed += 1; cats_costed.add("motor")
            base_breakdown.append({"kind": "motor", "label": note or f"{typed['motor_w']}W {place} motor",
                                   "cost": b, "method": "spec_estimate"})
    # The frameset is never parsed as a branded part, so its (large, material-driven)
    # cost was previously missing from the base -- inflating value_ratio for carbon
    # bikes. Cost it from the typed frame material + suspension (full-suspension frames
    # carry a premium; unknown material defaults to aluminium).
    if "frame" not in cats_costed:
        mat = typed.get("frame_material")
        # quality steel (chromoly/4130/Reynolds/Columbus) costs MORE than aluminium,
        # unlike the cheap hi-tensile/Q235 steel that the "steel" tier prices below it;
        # split it out for costing only (the displayed frame_material stays "steel").
        if mat == "steel" and re.search(r"chrom|cro-?mo|\b4130\b|reynolds|columbus",
                                        find_spec(flatten_grouped(model.get("specs") or {}), "frame"), re.I):
            mat = "chromoly"
        b, note = heuristic_retail({"category": "frame",
                       "attributes": {"material": mat,
                                      "full_suspension": typed.get("suspension") == "full"}})
        if b:
            base_total += b; costed += 1; cats_costed.add("frame")
            base_breakdown.append({"kind": "frame", "label": note, "cost": b,
                                   "method": "spec_estimate"})
    base = round(base_total, 2) if costed else None
    value_ratio = None
    if (price and base and costed >= _VALUE_MIN_PARTS
            and _VALUE_CORE <= cats_costed):
        value_ratio = round(price / base, 3)
    return {
        "parts_identified": identified,
        "parts_priced": priced,
        "parts_researched": researched,     # parts backed by a real lookup (vs estimate)
        "parts_costed": costed,
        "component_retail_value_usd": round(retail_total, 2) if retail_n else None,
        "component_base_value_usd": base,
        "value_ratio": value_ratio,
        # parts cost as a fraction of retail price (replaces the old separate BOM file)
        "bom_pct": round(base / price, 4) if base and price else None,
        # every line summing to component_base_value_usd (parsed parts + spec estimates)
        "base_breakdown": sorted(base_breakdown, key=lambda x: -x["cost"]),
    }


# Curated "uncommon features" — premium/notable equipment surfaced in their own card
# (replaces the removed Feature score). Each is shown only when the bike actually has it.
# Sourced from typed notable_tech / connectivity, plus a couple of keyword scans.
def uncommon_features(typed: dict, blob: str) -> list:
    nt = set(typed.get("notable_tech") or [])
    conn = set(typed.get("connectivity") or [])
    out = []
    # security & tracking
    if "gps" in conn:                 out.append("GPS Tracking")
    if "find my" in nt:               out.append("Find My")
    if "anti-theft" in nt or "alarm" in conn: out.append("Anti-Theft Alarm")
    if "fingerprint unlock" in nt:    out.append("Fingerprint Unlock")
    # smart system
    if "app" in conn:                 out.append("App Control")
    if re.search(r"over[\s-]?the[\s-]?air|firmware update|\bota\b", blob): out.append("Over-the-air Updates")
    if "smart helmet" in blob:        out.append("Smart Helmet")
    if "CANbus system" in nt:         out.append("CANbus System")
    # premium drivetrain
    if "electronic shifting" in nt:   out.append("Electronic Shifting")
    if "internal gear hub" in nt:     out.append("Internal Gear Hub")
    if "belt drive" in nt:            out.append("Belt Drive")
    if re.search(r"pinion|rohloff", blob): out.append("Gearbox (Pinion/Rohloff)")
    if "high-end drivetrain" in nt:   out.append("High-End Drivetrain")
    # premium ride kit
    if (typed.get("frame_material") or "").lower() == "carbon": out.append("Carbon Frame")
    if "dropper post" in nt:          out.append("Dropper Post")
    if "dual-battery" in nt:          out.append("Dual Battery")
    if "regen braking" in nt:         out.append("Regen Braking")
    if "ABS" in nt:                   out.append("ABS")
    if "4-piston brakes" in nt:       out.append("4-Piston Brakes")
    return out


# ---- All-Terrain: heavy, big-battery, capable adventure bikes (vs eMTB) -------------
_AT_EXEMPT = {"eMoto", "Cargo", "Trike", "Mountain (eMTB)", "All-Terrain"}


def _max_tire_in(model: dict):
    """Widest parsed tire (inches) on a model, or None."""
    ws = []
    for fields in (model.get("specs") or {}).values():
        if isinstance(fields, dict):
            for v in fields.values():
                if isinstance(v, dict) and v.get("_kind") == "tire" and isinstance(v.get("width_in"), (int, float)):
                    ws.append(v["width_in"])
    return max(ws) if ws else None


def _pctile(xs: list, q: int):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    return statistics.quantiles(xs, n=100)[q - 1] if len(xs) >= 2 else None


def promote_all_terrain(models: list, typed_by_id: dict) -> list:
    """Reclassify non-eMTB bikes to All-Terrain when they're heavier + longer-range than an
    eMTB and capable (wide tires / extra power / full suspension). Thresholds are eMTB-
    relative (battery ≥ P85, weight ≥ P90). Keyword All-Terrain already won via taxonomy.
    Returns the borderline list (close but not firm) for review. Run before cohorts."""
    bat_min = _pctile([typed_by_id[m["id"]].get("battery_wh") for m in models
                       if m.get("product_type") == "Mountain (eMTB)"], 85)
    wt_p90 = _pctile([typed_by_id[m["id"]].get("weight_lb") for m in models
                      if m.get("product_type") == "Mountain (eMTB)"], 90)
    wt_p85 = _pctile([typed_by_id[m["id"]].get("weight_lb") for m in models
                      if m.get("product_type") == "Mountain (eMTB)"], 85)
    border = []
    if not (bat_min and wt_p90):
        return border
    for m in models:
        if m.get("product_type") in _AT_EXEMPT:
            continue
        t = typed_by_id[m["id"]]
        tire = _max_tire_in(m)
        if tire is not None and tire > 4:               # >4" stays Fat Tire
            continue
        if (t.get("battery_wh") or 0) < bat_min:        # gate: big battery (≥ eMTB P85)
            continue
        signals = sum([
            (t.get("motor_peak_w") or 0) >= 1000 or (t.get("motor_w") or 0) >= 1000,  # extra power
            tire is not None and 2.8 <= tire <= 4.0,                                  # wide (vs eMTB)
            t.get("suspension") == "full",                                            # full suspension
        ])
        heavy = (t.get("weight_lb") or 0) >= wt_p90
        if heavy and signals >= 1:
            m["product_type"] = "All-Terrain"
            m["product_types"] = ["All-Terrain"]
        elif ((t.get("weight_lb") or 0) >= (wt_p85 or wt_p90)) or signals >= 1:
            border.append({"id": m["id"], "brand": m["brand"], "model": m["model"],
                           "current_type": m["product_type"], "battery_wh": t.get("battery_wh"),
                           "weight_lb": t.get("weight_lb"), "tire_in": tire, "signals": signals})
    return border


def _highlights(typed: dict, folding: bool = False) -> list:
    # "torque sensor" is intentionally NOT a highlight chip — it's shown as a
    # dedicated card icon, so listing it here would be redundant.
    out = [t for t in typed.get("notable_tech", []) if t != "torque sensor"]
    # NB hydraulic disc brakes are deliberately NOT a highlight: ~80% of tracked
    # e-bikes have them, so they don't differentiate.
    if typed.get("frame_material") == "carbon":
        out.append("carbon frame")
    if typed.get("suspension") == "full":
        out.append("full suspension")
    if folding:
        out.append("folding")
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
    ap.add_argument("-i", "--input", default=str(DATA / "current" / "active" / "ebike.json"))
    ap.add_argument("--catalog", default=str(DATA / "component_catalog.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    rehydrate(doc)   # tolerate an already-interned build (no-op on an inline one)
    models = doc.get("models", [])

    # Full component catalog entries (key -> entry) for the value roll-ups and the
    # per-part heuristic fallback.
    catalog_entries = {}
    try:
        catalog_entries = json.load(open(args.catalog)).get("components") or {}
    except FileNotFoundError:
        pass

    # Pass 1 - typed specs, plus price + bom + component values folded in for
    # the fleet distributions. BOM% is now derived from the catalog-based component base
    # (component_quality.bom_pct), so there's no separate component_cost_estimates.json.
    typed_by_id = {}
    cq_by_id = {}
    for m in models:
        t = extract_typed_specs(m)
        # frame_sizes is always a non-empty array (single-size = collection of one)
        m["frame_sizes"] = _ensure_frame_sizes(m, t)
        m["frame_size_count"] = len(m["frame_sizes"])
        # Structural eMoto: moto-class power (>=2000W nominal OR >=4000W peak) makes a
        # bike an eMoto even when it isn't NAMED moto/moped — no pedal-assist commuter
        # runs these numbers (Magician Alpha 3000W/5000W peak, 72V, 139 lb). Done here
        # (not normalize) so AWD bikes whose watts live in a Rated-Power row are caught
        # via the typed value. Bikes with their own identity (Cargo/Trike/eMTB) are kept.
        if (m.get("product_type") not in ("eMoto", "Cargo", "Trike", "Mountain (eMTB)")
                and ((t.get("motor_w") or 0) >= 2000 or (t.get("motor_peak_w") or 0) >= 4000)):
            m["product_type"] = "eMoto"
            m["product_types"] = ["eMoto"]
        # One type per bike now (see normalize._product_types) — we no longer ADD a
        # secondary Hybrid / Fitness tag. We DO still reclassify: a bike whose single
        # type is Hybrid / Fitness but is clearly heavy and not named hybrid/fitness
        # (a stale fed-back label, e.g. Velotric Summit 62 lb) drops to Commuter / Urban.
        w = t.get("weight_lb")
        if (HYBRID_FITNESS in (m.get("product_types") or [])
                and isinstance(w, (int, float)) and w > HYBRID_MAX_WEIGHT_LB
                and not re.search(r"hybrid|fitness", m.get("model") or "", re.I)):
            kept = [x for x in m["product_types"] if x != HYBRID_FITNESS]
            m["product_types"] = kept or ["Commuter / Urban"]
            m["product_type"] = m["product_types"][0]
        t["price"] = m.get("price")
        cq = component_quality(m, catalog_entries, m.get("price"), t)
        cq_by_id[m["id"]] = cq
        t["bom_pct"] = cq["bom_pct"]      # parts base / price, from the catalog
        t["component_retail_value_usd"] = cq["component_retail_value_usd"]
        t["value_ratio"] = cq["value_ratio"]
        typed_by_id[m["id"]] = t

    # All-Terrain promotion (eMTB-relative: heavier + bigger battery + capable). Runs
    # after Pass 1 (typed available) and before cohorts so the new type gets its own cohort.
    at_border = promote_all_terrain(models, typed_by_id)
    json.dump({"count": sum(1 for m in models if m.get("product_type") == "All-Terrain"),
               "borderline": at_border},
              open(DATA / "current" / "all_terrain_audit.json", "w"), indent=2, ensure_ascii=False)

    # Fleet field distributions (for the detail-page DistributionPlot) stay fleet-wide.
    stats = build_stats(typed_by_id)

    # --- Per-type cohorts: every score ranks a bike against its PRIMARY-type peers,
    # not the whole fleet. Cohorts are strict (no shrinkage), so small types still
    # rank within themselves. flags_by_id memoizes each bike's feature set.
    flags_by_id = {m["id"]: feature_flags(typed_by_id[m["id"]], m) for m in models}
    # broader equipment universe for standout badges (separate from the score's flags)
    st_flags_by_id = {m["id"]: standout_features(typed_by_id[m["id"]], m) for m in models}
    cohorts = defaultdict(list)
    for m in models:
        cohorts[m.get("product_type") or "Commuter / Urban"].append(m["id"])

    # Per-type field distributions for the detail-page "how it compares to other
    # <type> bikes" plot (the fleet `stats` still drive the global filter bounds).
    stats_by_type = {typ: build_stats({i: typed_by_id[i] for i in ids})
                     for typ, ids in cohorts.items()}

    RANK_FIELDS = NUMERIC_FIELDS + ["price", "value_ratio"]
    cohort_sorted, cohort_wt, cohort_prev, cohort_raws = {}, {}, {}, {}
    st_prev = {}   # per-type prevalence of each standout-equipment feature
    for typ, ids in cohorts.items():
        st_cnt = Counter(fl for i in ids for fl in st_flags_by_id[i])
        st_prev[typ] = {fl: c / len(ids) for fl, c in st_cnt.items()}
        cohort_sorted[typ] = {
            f: sorted(v for v in (typed_by_id[i].get(f) for i in ids)
                      if isinstance(v, (int, float)))
            for f in RANK_FIELDS
        }
        n = len(ids)
        cnt = Counter(fl for i in ids for fl in flags_by_id[i])
        # IDF weight: a feature ALL peers share (cnt == n) -> log(1) = 0 (not
        # distinctive); one only this bike has -> log(n) (max). Rarer = worth more.
        cohort_wt[typ] = {fl: math.log(n / c) for fl, c in cnt.items()}
        cohort_prev[typ] = {fl: c / n for fl, c in cnt.items()}
        cohort_raws[typ] = sorted(
            sum(cohort_wt[typ][fl] for fl in flags_by_id[i]) for i in ids)

    # Pass 2 - cohort-relative percentiles + scores, written back into each model.
    for m in models:
        t = typed_by_id[m["id"]]
        typ = m.get("product_type") or "Commuter / Urban"
        cs = cohort_sorted[typ]
        t.pop("bom_pct", None)
        t.pop("price", None)                 # price already lives at model top level
        # component values are reported under component_quality, not specs_typed
        t.pop("component_retail_value_usd", None)
        value_ratio = t.pop("value_ratio", None)
        pct = compute_percentiles({**t, "price": m.get("price")}, cs)
        price_pct = pct.get("price_pct")
        # value score: rank price/parts-cost low→high within type, inverted so best = highest
        value_rank = (percentile_rank(value_ratio, cs["value_ratio"])
                      if value_ratio is not None and cs["value_ratio"] else None)
        # feature score: rank this bike's rarity-weighted feature sum within its cohort
        my_flags = flags_by_id[m["id"]]
        raw = sum(cohort_wt[typ].get(fl, 0.0) for fl in my_flags)
        feature_score = (round(percentile_rank(raw, cohort_raws[typ]) * 100, 1)
                         if cohort_raws[typ] else None)
        # transparency: the features this bike has that are rarest among its peers
        prev = cohort_prev[typ]
        feature_notable = sorted((fl for fl in my_flags if prev.get(fl, 1) < 0.5),
                                 key=lambda fl: prev.get(fl, 1))[:4]
        m["analysis"] = {
            "specs_typed": t,
            "percentiles": pct,
            "scores": compute_scores(pct, price_pct, value_rank, feature_score),
            "feature_notable": feature_notable,
            "primary_type": typ,
            "highlights": _highlights(t, m.get("folding")),
            # what makes this bike stand out from its type peers: top-quartile magnitude
            # specs + equipment uncommon in the cohort (merged badge set the UI renders)
            "standouts": standouts(pct, t, st_flags_by_id[m["id"]], st_prev[typ], m),
            "uncommon_features": uncommon_features(
                t, " ".join([*(str(v) for v in flatten_grouped(m.get("specs") or {}).values()),
                             *(a.get("name", "") for a in (m.get("included_accessories") or []))]).lower()),
            "component_quality": cq_by_id[m["id"]],
        }

    doc["analysis_stats"] = stats
    doc["analysis_stats_by_type"] = stats_by_type
    doc["analysis_disclaimer"] = (
        "Typed specs are parsed from each bike's published specifications. "
        "Percentiles and 0-100 scores are heuristic comparison aids, each ranked "
        "against the bike's PRIMARY-TYPE peers -- there is no composite score; rank "
        "on whichever criteria matter."
    )
    doc["generated_at"] = datetime.now(timezone.utc).isoformat()

    Path(args.input).write_text(json.dumps(doc, indent=2, ensure_ascii=False))

    enriched = sum(1 for m in models if "analysis" in m)
    miss_price = sum(1 for m in models if m["analysis"]["scores"].get("value") is None)
    print(f"Wrote {Path(args.input).name}: analysis on {enriched}/{len(models)} models, "
          f"{len(stats)} field distributions ({miss_price} without a value score).")


if __name__ == "__main__":
    main()
