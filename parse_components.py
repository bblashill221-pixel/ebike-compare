#!/usr/bin/env python3
"""
Parse free-text component spec values into structured fields.

Each recognized component (derailleur, fork, brake, motor, battery, tire, …) has a
parser that pulls out the expected attributes (manufacturer, speeds, travel,
power, etc.). Whatever is NOT parsed is left in `details` so no information is
lost. `parse_component(field, value, brand)` returns the structured dict, or None
when `field` isn't a known component (leave it a plain string then).

Used by spec_groups.group_specs (so it lands in every JSON file).
"""
from __future__ import annotations

import re

# ----------------------------- brand vocabularies -----------------------------
SHIFTING = ("Shimano", "SRAM", "microSHIFT", "MicroShift", "Enviolo", "NuVinci",
            "Sturmey Archer", "Sturmey-Archer", "Pinion", "LTWOO", "Sensah",
            "Box", "Gates", "KMC", "Sunrace", "Sun Race")
BRAKES = ("Tektro", "Shimano", "SRAM", "Magura", "TRP", "Hayes", "Bengal", "Zoom",
          "Nutt", "Promax", "Logan", "Dorado", "Juin Tech", "Clarks", "Apse")
SUSPENSION = ("RockShox", "Rock Shox", "SR Suntour", "Suntour", "Fox", "Manitou",
              "X-Fusion", "DNM", "Mozo", "RST", "Marzocchi", "Mastodon", "Zoom")
MOTORS = ("Bosch", "Bafang", "Shengyi", "Ananda", "Das-Kit", "DAS-KIT", "Dapu",
          "Mivice", "Yamaha", "Brose", "Mahle", "Hyena", "Aikema", "AKM", "MPF",
          "TranzX", "Ultro", "Globe")
CELLS = ("Samsung", "LG", "Panasonic", "Molicel", "Sony", "BAK", "EVE", "CATL",
         "Lishen")
TIRES = ("Maxxis", "Kenda", "CST", "Innova", "Schwalbe", "Vee", "WTB",
         "Continental", "Chao Yang", "ChaoYang", "Goodyear", "Pirelli", "Tannus",
         "Michelin", "Sunlite", "Ralson")
SADDLES = ("Selle Royal", "SelleRoyal", "Selle", "Velo", "WTB", "Brooks", "SDG",
           "DDK", "Cionlli")
DISPLAYS = ("Bosch", "King-Meter", "KingMeter", "Bafang", "APT", "Ananda")
HOUSE = {"specialized": ("Globe", "Roval", "Specialized")}


def _brands_for(brands: tuple, brand: str | None) -> list:
    """Category brands + the bike's own/house brand, longest first."""
    cand = list(brands)
    if brand:
        cand += list(HOUSE.get(brand, ())) + [brand.title()]
    return sorted(set(cand), key=len, reverse=True)


def _find_brand(text: str, brands: list):
    """First-occurring known brand in `text`; returns (canonical, text_without)."""
    best = None
    for b in brands:
        m = re.search(r"(?<![A-Za-z])" + re.escape(b) + r"(?![A-Za-z])", text, re.I)
        if m and (best is None or m.start() < best[1]):
            best = (b, m.start(), m.end())
    if not best:
        return None, text
    return best[0], (text[:best[1]] + text[best[2]:])


def _clean(s: str) -> str:
    """Tidy the leftover string for `details` (collapse space, trim stray seps)."""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[,;\s]+\)", ")", s)          # ", )" -> ")"
    s = re.sub(r"\(\s*[,;]\s*", "(", s)       # "(, " -> "("
    s = re.sub(r"\(\s*\)", "", s)             # empty "()" -> ""
    s = re.sub(r"\s+([,;.])", r"\1", s)
    s = re.sub(r"(?:[,;/&]\s*){2,}", ", ", s)
    s = re.sub(r"\s{2,}", " ", s)
    if s.count("(") != s.count(")"):          # drop orphaned parens
        s = s.replace("(", "").replace(")", "")
    return s.strip(" ,;:/&-–—.")


def _consume(text: str, pattern: str):
    """If `pattern` matches, return (match, text_with_match_removed); else (None, text)."""
    m = re.search(pattern, text, re.I)
    if not m:
        return None, text
    return m, text[:m.start()] + text[m.end():]


def _speeds(text: str):
    for pat in (r"(\d{1,2})\s*[-\s]?(?:speed|spd|sp)\b", r"\(\s*(\d{1,2})\s*-?\s*spd\)",
                r"speed\s*:?\s*(\d{1,2})"):
        m, text2 = _consume(text, pat)
        if m:
            return int(m.group(1)), text2
    return None, text


_CVT = r"enviolo|nuvinci|\bcvt\b|continuously[\s-]?variable|infinitely[\s-]?geared|stepless|automatiq"


# --------------------------------- parsers -----------------------------------

def _derailleur(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SHIFTING, brand))
    if man:
        out["manufacturer"] = man
    if re.search(_CVT, v, re.I):
        out["gearing"] = "continuously_variable"
    else:
        sp, rest = _speeds(rest)
        if sp:
            out["speeds"] = sp
    out["details"] = _clean(rest)
    return out


def _cassette(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SHIFTING, brand))
    if man:
        out["manufacturer"] = man
    m, rest = _consume(rest, r"(\d{1,2}\s*[-–]\s*\d{1,2})\s*t\b")   # cog range 11-32T
    if m:
        out["cog_range"] = re.sub(r"\s*", "", m.group(1)).replace("–", "-") + "T"
    if re.search(_CVT, v, re.I):
        out["gearing"] = "continuously_variable"
    else:
        sp, rest = _speeds(rest)
        if sp:
            out["speeds"] = sp
    out["details"] = _clean(rest)
    return out


def _chain(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SHIFTING, brand))
    if man:
        out["manufacturer"] = man
    m, rest = _consume(rest, r"(\d{2,3})\s*(?:l\b|link)")           # 154L / 122 Link
    if m:
        out["links"] = int(m.group(1))
    # chains are multi-speed-compatible (7/8); leave the speed string in details
    out["details"] = _clean(rest)
    return out


def _crankset(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SHIFTING + ("Prowheel", "Lasco"), brand))
    if man:
        out["manufacturer"] = man
    m, rest = _consume(rest, r"(\d{3})\s*mm")                       # crank arm length
    if m:
        out["length_mm"] = int(m.group(1))
    m, rest = _consume(rest, r"(\d{2})\s*t\b")                      # chainring teeth
    if m:
        out["chainring_t"] = int(m.group(1))
    out["details"] = _clean(rest)
    return out


def _fork(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SUSPENSION, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if re.search(r"\brigid\b|no suspension", low):
        out["type"] = "rigid"
    elif re.search(r"\bair\b", low):
        out["type"] = "air"
    elif re.search(r"coil|spring|mechanical|hydraulic|suspension|lockout", low):
        out["type"] = "coil"
    if out.get("type") != "rigid":
        m, rest = _consume(rest, r"(\d{2,3})\s*mm(?:\s*travel)?")
        if m:
            out["travel_mm"] = int(m.group(1))
    out["lockout"] = bool(re.search(r"lock[\s-]?out", low))
    out["thru_axle"] = bool(re.search(r"thru[\s-]?axle|thru axle", low))
    out["details"] = _clean(rest)
    return out


def _shock(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SUSPENSION, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    out["type"] = "air" if "air" in low else ("coil" if re.search(r"coil|spring", low) else None)
    if out["type"] is None:
        del out["type"]
    m, rest = _consume(rest, r"(\d{2,3}\s*[x×]\s*\d{2,3}(?:\.\d)?\s*mm)")  # eye-to-eye x stroke
    if m:
        out["size"] = re.sub(r"\s*", "", m.group(1)).replace("×", "x")
    out["details"] = _clean(rest)
    return out


def _brake(v, brand, rotor_text=""):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(BRAKES, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if "hydraulic" in low:
        out["actuation"] = "hydraulic"
    elif re.search(r"mechanical|cable", low):
        out["actuation"] = "mechanical"
    if "disc" in low:
        out["kind"] = "disc"
    elif re.search(r"\brim\b|\bv-?brake", low):
        out["kind"] = "rim"
    m, rest = _consume(rest, r"(\d)\s*[-\s]?piston")
    if m:
        out["pistons"] = int(m.group(1))
    blob = v + " " + (rotor_text or "")
    md = re.search(r"(\d{3})\s*mm", blob)            # rotor diameter (160/180/203)
    if md:
        out["rotor_mm"] = int(md.group(1))
        rest = re.sub(r"\d{3}\s*mm", "", rest, count=1)
    mt = re.search(r"(\d(?:\.\d)?)\s*mm\s*(?:thick|thickness)|x\s*(\d(?:\.\d)?)\s*mm", blob, re.I)
    if mt:
        out["rotor_thickness_mm"] = float(mt.group(1) or mt.group(2))
    out["details"] = _clean(rest)
    return out


def _motor(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(MOTORS, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if re.search(r"mid[\s-]?drive|mid[\s-]?motor", low):
        out["placement"] = "mid"
    elif re.search(r"\bhub\b", low):
        out["placement"] = "hub"
    mp = re.search(r"(\d{3,4})\s*w[^.]{0,14}peak|peak[^0-9]{0,14}(\d{3,4})\s*w", low)
    if mp:
        out["peak_w"] = int(mp.group(1) or mp.group(2))
    cont = re.sub(r"(\d{3,4})\s*w[^.]{0,14}peak|peak[^0-9]{0,14}\d{3,4}\s*w", " ", low)
    m, _ = _consume(cont, r"(\d{3,4})\s*w\b")
    if m:
        out["power_w"] = int(m.group(1))
    m = re.search(r"(\d{2,3})\s*n[·.\s]?m", low)
    if m:
        out["torque_nm"] = int(m.group(1))
    m = re.search(r"(\d{2,3})\s*v\b", low)
    if m:
        out["voltage_v"] = int(m.group(1))
    # strip the matched numbers (and their orphaned qualifiers) from details
    for pat in (r"\d{3,4}\s*w\s*\(?\s*peak\)?", r"peak[^0-9]{0,14}\d{3,4}\s*w",
                r"\d{3,4}\s*w", r"\d{2,3}\s*n[·.\s]?m", r"\d{2,3}\s*v\b",
                r"\((?:sustained|continuous|nominal|rated|peak|max\.?\s*power|cont\.?)\)",
                r"\btorque\b"):
        rest = re.sub(pat, "", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _battery(v, brand):
    rest = v
    out = {}
    cell, _ = _find_brand(v, list(CELLS))
    if cell:
        out["cell_brand"] = cell
    man, rest = _find_brand(rest, _brands_for(("Bosch",), brand))
    if man:
        out["manufacturer"] = man
    m = re.search(r"(\d{3,4})\s*wh", v, re.I)
    if m:
        out["capacity_wh"] = int(m.group(1))
    m = re.search(r"(\d{2,3})\s*v\b", v, re.I)
    if m:
        out["voltage_v"] = int(m.group(1))
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*ah", v, re.I)
    if m:
        out["amphours_ah"] = float(m.group(1))
    m = re.search(r"\b(21700|18650|20700)\b", v)
    if m:
        out["cell_format"] = m.group(1)
    out["removable"] = bool(re.search(r"removable", v, re.I))
    # leftover details: drop the numbers/cell brand we captured
    if cell:
        rest = re.sub(r"(?<![A-Za-z])" + re.escape(cell) + r"(?![A-Za-z])", "", rest, flags=re.I)
    for pat in (r"\d{3,4}\s*wh", r"\d{2,3}\s*v\b", r"\d{1,2}(?:\.\d)?\s*ah",
                r"\b(?:21700|18650|20700)\b\s*(?:cells)?"):
        rest = re.sub(pat, "", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _tire(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(TIRES, brand))
    if man:
        out["manufacturer"] = man
    # wheel x width, e.g. 26x4.0, 27.5 x 2.20, 29x2.4", 700x45c. The (?<!\d) stops
    # the wheel size being split out of a 3-digit number like 700.
    m, rest = _consume(rest, r"(?<!\d)(\d{2,3}(?:\.\d)?\s*[x×]\s*\d{1,2}(?:\.\d+)?\s*[c\"”]?)")
    if m:
        out["size"] = re.sub(r"\s+", "", m.group(1)).replace("×", "x").rstrip('"”')
    out["tubeless"] = bool(re.search(r"tubeless|\btlr\b", v, re.I))
    out["details"] = _clean(rest)
    return out


def _display(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(DISPLAYS, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if "touch" in low:
        out["type"] = "touchscreen"
    elif re.search(r"color|colour|tft", low):
        out["type"] = "color"
    elif re.search(r"\blcd\b|\bled\b|monochrome", low):
        out["type"] = "lcd"
    out["details"] = _clean(rest)
    return out


def _resolver(field: str):
    """Map a (snake) field name to a component parser via tolerant substring rules,
    so label variants (hydraulic_brakes, front_fork, motor_hub, …) are covered."""
    f = field
    if "derailleur" in f or "shifter" in f or "shift_lever" in f or f == "e_shifter":
        return _derailleur
    if "cassette" in f or "freewheel" in f:
        return _cassette
    if f == "chain":
        return _chain
    if "crank" in f:
        return _crankset
    if "fork" in f or f == "suspension":
        return _fork
    if "shock" in f or f == "rear_suspension":
        return _shock
    if "brake" in f and "rotor" not in f:
        return _brake
    if "motor" in f or f == "drive_unit":
        return _motor
    if f == "battery":
        return _battery
    if "tire" in f or "tyre" in f:
        return _tire
    if "display" in f:
        return _display
    return None


def parse_component(field: str, value, brand: str | None = None,
                    siblings: dict | None = None):
    """Structured dict for a known component field, else None. `siblings` lets the
    brake parser borrow a separate rotor field for diameter/thickness."""
    fn = _resolver(field)
    if fn is None or not isinstance(value, str) or not value.strip():
        return None
    if fn is _brake:
        rotor = ""
        for k, sv in (siblings or {}).items():
            if "rotor" in k and isinstance(sv, str):
                rotor += " " + sv
        return _brake(value, brand, rotor)
    return fn(value, brand)
