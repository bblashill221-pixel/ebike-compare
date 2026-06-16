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

from spec_parse import num, find_spec, blob, kg_to_lb, percentile_rank, height_range_in
from spec_groups import flatten_grouped
from component_catalog import iter_components

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
            or num(rf"peak[^0-9,()/]{{0,14}}(\d{{3,4}})\s*{_W}", txt))
    cont_txt = re.sub(rf"\d{{3,4}}\s*{_W}\s*peak", " ", txt, flags=re.I)
    cont_txt = re.sub(rf"peak[^0-9,()/]{{0,14}}\d{{3,4}}\s*{_W}", " ", cont_txt, flags=re.I)
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
    return round(nm) if nm else None


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
    # wording like "mid-step" from false-matching.
    return ("mid" if re.search(r"mid[- ]?(drive|motor)|bottom bracket|\bmid\b(?![\s-]?step)", txt)
            else "hub")


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
    if re.search(r"\brim brake|v[-\s]?brake|cantilever|linear[-\s]?pull|coaster", txt):
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
    txt = find_spec(specs, "derailleur", "cassette", "freewheel", "chain", "drivetrain",
                    "shift", "gear", "transmission").lower()
    if not txt:
        return None
    if re.search(r"belt|gates|carbon drive", txt):
        return "belt"
    if re.search(r"enviolo|cvt|nuvinci|internal gear|igh|auto[- ]?shift"
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
    # "carbon" means carbon *fiber* ONLY. "carbon steel" / "high|low|mid|mild
    # carbon" are STEEL, and a "Gates Carbon Drive" belt is a DRIVETRAIN, not a
    # frame -- the lookbehinds drop the steel qualifiers and the lookahead drops
    # "carbon steel/drive/belt".
    if re.search(r"(?<!high )(?<!high-)(?<!low )(?<!low-)(?<!mid )(?<!mid-)"
                 r"(?<!medium )(?<!medium-)(?<!mild )(?<!mild-)"
                 r"carbon(?![\s-]*(?:steel|drive|belt))", txt):
        return "carbon"
    # A named aluminium alloy (6061/6063/7005; A356/A380 castings) means the frame
    # is aluminium even when the text also says "steel" (a mislabelled casting or a
    # mixed front/rear), so it's checked before the steel rule.
    if re.search(r"alum|aluminium|\balloy\b|6061|6063|7005"
                 r"|\ba3\d{2}\b|\ba380\b|\b\d{4}\s*-?\s*al\b|\bal[-\s]?\d{4}\b", txt):
        return "aluminum"
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
    # read the sensor / pedal-assist rows only -- NOT the motor row, whose torque
    # RATING ("Max Torque 80Nm") is not a torque SENSOR. A "speed sensor" is the
    # same thing as a cadence sensor.
    txt = find_spec(specs, "sensor", "pedal").lower()
    has_t = "torque" in txt
    has_c = "cadence" in txt or bool(re.search(r"speed[\s-]?sensor", txt))
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
        (r"dual[- ]?battery|second battery|two batteries", "dual-battery"),
        (r"anti[- ]?theft|gps tracking|alarm", "anti-theft"),
        (r"fingerprint", "fingerprint unlock"),
        (r"torque sensor", "torque sensor"),
        (r"mid[- ]?drive", "mid-drive motor"),
        # uncommon premium kit
        (r"dropper", "dropper post"),
        (r"quad[- ]?piston|four[- ]?piston|4[- ]?piston", "4-piston brakes"),
        (r"\bdi2\b|\baxs\b|electronic shift", "electronic shifting"),
        (r"deore xt|\bxtr\b|\bslx\b|\bx01\b|\bxx1\b|gx eagle", "high-end drivetrain"),
        (r"enviolo|nuvinci|internal[- ]?gear|\bigh\b", "internal gear hub"),
    ]
    for pat, label in checks:
        if re.search(pat, b):
            out.append(label)
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


def _fit_height(model: dict) -> tuple[float | None, float | None]:
    """(min_in, max_in) the bike can fit, enveloped across every published
    rider-height range and frame size, or (None, None) -- unrounded inches, so the
    caller can derive precise mm bounds for the metric search. Reads the GROUPED
    geometry (model.specs.geometry) where a per-size dict is preserved -- the
    flattened specs would stringify it -- so "any frame size that fits" is captured."""
    geo = (model.get("specs") or {}).get("geometry") or {}
    lo = hi = None
    for k, v in geo.items():
        kl = k.lower()
        if "rider" in kl and "height" in kl:
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
            kl = k.lower()
            if "rider" in kl and "height" in kl and isinstance(v, str):
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
    fs = model.get("frame_sizes")
    if fs:
        return fs
    lo, hi = typed.get("fit_height_min_in"), typed.get("fit_height_max_in")
    fmt = lambda i: f"{int(i) // 12}'{int(i) % 12}\"" if i is not None else None
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
        "suspension": _suspension(specs),
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
    # transparency (mirrors curated_overrides)
    ext = HTML_EXTRACTED.get(model.get("id")) or {}
    applied = []
    for f, e in ext.items():
        if typed.get(f) in (None, "", []):
            typed[f] = e.get("value")
            applied.append(f)
    if applied:
        model["html_extracted"] = sorted(applied)
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
    fields = NUMERIC_FIELDS + ["price", "bom_pct",
                               "component_retail_value_usd", "component_wholesale_value_usd"]
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


def compute_scores(typed: dict, stats: dict, bom_pct, price_pct, pct: dict) -> dict:
    s = {}

    # --- numeric dimensions: field-relative RANK percentile (0-100) ---
    # Rank, not magnitude, so a handful of extreme bikes (e.g. eMoto peak/wheel
    # torque of 200-430 Nm) don't compress everyone else's score. power = motor
    # wattage; torque is its own dimension (was folded into power).
    def _rank(field):
        p = pct.get(f"{field}_pct")
        return round(p * 100, 1) if p is not None else None
    s["power"] = _rank("motor_w")
    s["torque"] = _rank("torque_nm")
    s["range"] = _rank("range_mi")
    s["battery"] = _rank("battery_wh")
    # price as affordability: cheaper ranks higher (price_pct is already inverted).
    s["price"] = round(price_pct * 100, 1) if price_pct is not None else None

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
    if typed.get("sensor_type") in ("torque", "torque + cadence"):
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
    if typed.get("sensor_type") in ("torque", "torque + cadence"):
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
    if typed.get("sensor_type") in ("torque", "torque + cadence"):
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


def component_quality(model: dict, part_prices: dict) -> dict:
    """Join the component catalog's price lookups back onto one bike: how many
    parsed parts were identified/priced, and TWO independent value roll-ups —
    aftermarket retail value and OEM wholesale value (each summed across the
    bike's part instances). Facts only — the two stand alone, never blended."""
    identified = priced = retail_n = wholesale_n = 0
    retail_total = wholesale_total = 0.0
    for key, _cat, _part in iter_components(model):
        identified += 1
        p = part_prices.get(key) or {}
        r, w = p.get("retail"), p.get("wholesale")
        if r is not None:
            retail_n += 1
            retail_total += r
        if w is not None:
            wholesale_n += 1
            wholesale_total += w
        if r is not None or w is not None:
            priced += 1
    return {
        "parts_identified": identified,
        "parts_priced": priced,
        "component_retail_value_usd": round(retail_total, 2) if retail_n else None,
        "component_wholesale_value_usd": round(wholesale_total, 2) if wholesale_n else None,
    }


def _highlights(typed: dict) -> list:
    out = list(typed.get("notable_tech", []))
    if typed.get("sensor_type") in ("torque", "torque + cadence") and "torque sensor" not in out:
        out.append("torque sensor")
    # NB hydraulic disc brakes are deliberately NOT a highlight: ~80% of tracked
    # e-bikes have them, so they don't differentiate.
    if typed.get("frame_material") == "carbon":
        out.append("carbon frame")
    if typed.get("suspension") == "full":
        out.append("full suspension")
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
    ap.add_argument("--catalog", default=str(DATA / "component_catalog.json"))
    args = ap.parse_args()

    doc = json.load(open(args.input))
    models = doc.get("models", [])

    # Part prices from the component catalog (key -> {retail, wholesale}).
    part_prices = {}
    try:
        cat = json.load(open(args.catalog))
        for key, e in (cat.get("components") or {}).items():
            am = e.get("aftermarket") or {}
            r, w = am.get("retail_usd"), am.get("wholesale_usd")
            if r is not None or w is not None:
                part_prices[key] = {"retail": r, "wholesale": w}
    except FileNotFoundError:
        pass

    # BOM lookup keyed by (brand, model name).
    bom = {}
    try:
        cd = json.load(open(args.costs))
        for r in cd.get("models", []):
            bom[(r.get("brand"), r.get("model"))] = r.get("bom_pct_of_retail")
    except FileNotFoundError:
        print(f"[!] {args.costs} not found; value scores will be null.")

    # Pass 1 - typed specs, plus price + bom + component values folded in for
    # the fleet distributions.
    typed_by_id = {}
    cq_by_id = {}
    for m in models:
        t = extract_typed_specs(m)
        # frame_sizes is always a non-empty array (single-size = collection of one)
        m["frame_sizes"] = _ensure_frame_sizes(m, t)
        m["frame_size_count"] = len(m["frame_sizes"])
        t["price"] = m.get("price")
        t["bom_pct"] = bom.get((m.get("brand"), m.get("model")))
        cq = component_quality(m, part_prices)
        cq_by_id[m["id"]] = cq
        t["component_retail_value_usd"] = cq["component_retail_value_usd"]
        t["component_wholesale_value_usd"] = cq["component_wholesale_value_usd"]
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
        # component values are reported under component_quality, not specs_typed
        t.pop("component_retail_value_usd", None)
        t.pop("component_wholesale_value_usd", None)
        pct = compute_percentiles({**t, "price": m.get("price")}, sorted_field)
        bom_rank = (percentile_rank(bom_pct, sorted_field["bom_pct"])
                    if bom_pct is not None and sorted_field["bom_pct"] else None)
        price_pct = pct.get("price_pct")
        m["analysis"] = {
            "specs_typed": t,
            "percentiles": pct,
            "scores": compute_scores(t, stats, bom_pct, price_pct, pct),
            "highlights": _highlights(t),
            "component_quality": cq_by_id[m["id"]],
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
