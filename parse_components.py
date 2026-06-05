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
        # prefer an mm value explicitly labeled "travel"; else the first mm that
        # isn't an offset/axle/spacing/rotor measurement.
        mt = re.search(r"(\d{2,3})\s*mm\s*(?:of\s+)?travel", v, re.I) \
            or re.search(r"travel[:\s]+(\d{2,3})\s*mm", v, re.I)
        if mt:
            out["travel_mm"] = int(mt.group(1))
            rest = rest.replace(mt.group(0), " ", 1)
        else:
            for mm in re.finditer(r"(\d{2,3})\s*mm", rest):
                tail = rest[mm.end():mm.end() + 12].lower()
                if not re.match(r"\s*(offset|spacing|axle|rotor|stanchion|steer)", tail):
                    out["travel_mm"] = int(mm.group(1))
                    rest = rest[:mm.start()] + " " + rest[mm.end():]
                    break
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


def _stem(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(
        ("Zoom", "Promax", "Kalloy", "UNO", "Satori", "Aerozine", "Brose"), brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if "carbon" in low:
        out["material"] = "carbon"
    elif re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    elif "steel" in low:
        out["material"] = "steel"
    if "quill" in low:
        out["type"] = "quill"
    elif re.search(r"thread\s*less|ahead", low):
        out["type"] = "threadless"
    elif "fold" in low:
        out["type"] = "folding"
    out["adjustable"] = bool(re.search(r"adjust", low))

    # AxBxC dimension form: steerer(28.6/22.2) x length x clamp(31.8/35).
    m3 = re.search(r"(\d{2}(?:\.\d)?)\s*[x*]\s*(\d{2,3})(?:\s*[x*]\s*(\d{2}(?:\.\d)?))?\s*mm", v)
    if m3:
        nums = [float(x) for x in m3.groups() if x]
        for n in nums:
            if n in (31.8, 35.0, 25.4) and "clamp_mm" not in out:
                out["clamp_mm"] = n
            elif n not in (28.6, 22.2, 31.8, 35.0, 25.4) and 25 <= n <= 160:
                out.setdefault("length_mm", int(n))
        rest = rest.replace(m3.group(0), " ", 1)
    mc = re.search(r"(?:Φ|ø)?\s*(31\.8|35|25\.4|22\.2)\s*mm", v)
    if mc and "clamp_mm" not in out:
        out["clamp_mm"] = float(mc.group(1))
        rest = rest.replace(mc.group(0), " ", 1)
    if "length_mm" not in out:
        ml = (re.search(r"(\d{2,3})\s*mm\s*(?:length|extension)", v, re.I)
              or re.search(r"(?:length|ext(?:ension)?)\s*:?\s*(\d{2,3})\s*mm?", v, re.I)
              or re.search(r"(?<![.\d])(\d{2,3})\s*mm\b", rest))
        if ml:
            out["length_mm"] = int(ml.group(1))
            rest = rest.replace(ml.group(0), " ", 1)
    angs = [int(x) for x in re.findall(r"(\d{1,3})\s*(?:°|deg)", v, re.I)]
    if angs:
        out["angle_deg"] = max(angs)
    for pat in (r"\d{1,3}\s*(?:°|deg(?:ree)?s?)", r"\b(?:rise|height|ext(?:ension)?|length)\b\s*:?",
                r"\badjustable\b|\beasy adjust\b"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _seatpost(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(
        ("SR Suntour", "Suntour", "X-Fusion", "XFusion", "Xfusion", "SRAM",
         "RockShox", "Rock Shox", "Fox", "Bike Yoke", "Kind Shock", "Brand-X",
         "PNW", "Satori", "Promax", "Exa", "TranzX"), brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if re.search(r"dropper|telescop|double extension|reverb|transfer|revive|\bmanic\b|\baxs\b", low):
        out["type"] = "dropper"
    elif re.search(r"suspension|travel", low):
        out["type"] = "suspension"
    if "carbon" in low:
        out["material"] = "carbon"
    elif re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    md = re.search(r"(?:Φ|ø|Ø)?\s*(27\.2|28\.6|30\.4|30\.9|31\.6|33\.9|34\.9)(?![\d.])", v)
    if md:
        out["diameter_mm"] = float(md.group(1))
        rest = rest.replace(md.group(0), " ", 1)
    mt = re.search(r"(\d{2,3})\s*mm\s*(?:travel|drop)|travel\s*:?\s*(\d{2,3})\s*mm?", v, re.I)
    if mt:
        out["travel_mm"] = int(mt.group(1) or mt.group(2))
    else:
        sizes = [int(x) for x in re.findall(r"s\d\s*:?\s*(\d{2,3})\s*mm", v, re.I)]
        if sizes:
            out["travel_mm"] = max(sizes)
    mo = re.search(r"(\d{1,2})\s*mm\s*offset", v, re.I)
    if mo:
        out["offset_mm"] = int(mo.group(1))
    rest2 = re.sub(r"\d{2,3}\s*mm\s*(?:travel|drop)", " ", rest, flags=re.I)
    ml = re.search(r"(?:length\s*:?\s*)?(\d{3})\s*mm", rest2, re.I) or re.search(r"[x*]\s*(\d{3})\b", rest2)
    if ml and 200 <= int(ml.group(1)) <= 700:
        out["length_mm"] = int(ml.group(1))
        rest = re.sub(re.escape(ml.group(0)), " ", rest, count=1)
    for pat in (r"(?:Φ|ø|Ø)?\s*\d{2}\.\d\b", r"\d{2,3}\s*mm\s*(?:travel|drop|length)?",
                r"\btravel\b\s*:?", r"\blength\b\s*:?", r"[x*]\s*\d{3}\b",
                r"\d{1,2}\s*mm\s*offset", r"s\d\s*:?\s*\d{2,3}\s*mm"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _handlebars(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(
        ("Zoom", "Promax", "Kalloy", "UNO", "Satori", "Aerozine"), brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    if "carbon" in low:
        out["material"] = "carbon"
    elif re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    elif "steel" in low:
        out["material"] = "steel"
    if "bmx" in low:
        out["type"] = "bmx"
    elif re.search(r"riser|rise", low):
        out["type"] = "riser"
    elif re.search(r"cruiser|swept|curved", low):
        out["type"] = "cruiser"
    elif re.search(r"\bflat\b|straight", low):
        out["type"] = "flat"
    mc = re.search(r"(31\.8|35|25\.4|22\.2)\s*mm?\s*(?:bar\s*)?clamp", v, re.I) \
        or re.search(r"[x*]\s*(31\.8|35|25\.4)\s*(?:mm)?", v) \
        or re.search(r"(?:Φ|ø|Ø)?\s*(31\.8|35)\s*mm", v)   # bar clamp is 31.8/35
    if mc:
        out["clamp_mm"] = float(mc.group(1))
    mw = (re.search(r"(\d{3})\s*mm\s*(?:width|wide)", v, re.I)
          or re.search(r"\b(?:width|w)\s*:?\s*(\d{3})", v, re.I)
          or re.search(r"[x*]\s*(\d{3})\s*mm", v)
          or re.search(r"(?<![.\d])(\d{3})\s*mm\b", rest))
    if mw and 500 <= int(mw.group(1)) <= 860:
        out["width_mm"] = int(mw.group(1))
    mr = re.search(r"(\d{1,3})\s*mm\s*rise|rise\s*:?\s*(\d{1,3})\s*mm", v, re.I)
    if mr:
        out["rise_mm"] = int(mr.group(1) or mr.group(2))
    mb = re.search(r"(\d{1,2})\s*[°*]\s*back\s*sweep", v, re.I)
    if mb:
        out["backsweep_deg"] = int(mb.group(1))
    mu = re.search(r"(\d{1,2})\s*[°*]\s*up\s*sweep", v, re.I)
    if mu:
        out["upsweep_deg"] = int(mu.group(1))
    for pat in (r"\d{3}\s*mm\s*(?:width|wide)?", r"\b(?:width|w)\s*:?\s*\d{3}",
                r"[x*]\s*\d{3}\s*mm?", r"(31\.8|35|25\.4|22\.2)\s*mm?\s*(?:bar\s*)?clamp",
                r"[x*]\s*(?:31\.8|35|25\.4|22\.2)", r"(?:Φ|ø|Ø)?\s*(?:31\.8|35)\s*mm",
                r"\d{1,3}\s*mm\s*rise", r"rise\s*:?",
                r"\d{1,2}\s*[°*]\s*(?:up|back)\s*sweep", r"\bclamp\b", r"\bwidth\b|\bwide\b"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _charger(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(("Bosch",), brand))
    if man:
        out["manufacturer"] = man
    ma = re.search(r"(\d+(?:\.\d)?)\s*a\b", v, re.I)
    if ma:
        out["amps_a"] = float(ma.group(1))
    mo = re.search(r"output\s*:?\s*(\d{2,3})\s*v", v, re.I) or re.search(r"(\d{2,3})\s*v", v, re.I)
    if mo:
        out["output_v"] = int(mo.group(1))
    for pat in (r"output\s*:?", r"\d+(?:\.\d)?\s*a\b", r"\d{2,3}\s*v"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _controller(v, brand):
    rest = v
    out = {}
    mv = re.search(r"(\d{2,3})\s*v", v, re.I)
    if mv:
        out["voltage_v"] = int(mv.group(1))
    ma = re.search(r"(\d{1,3})\s*a\b", v, re.I)
    if ma:
        out["amps_a"] = int(ma.group(1))
    for pat in (r"\d{2,3}\s*v", r"\d{1,3}\s*a\b"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _sensor(v, brand):
    out, low = {}, v.lower()
    types = [t for t in ("torque", "cadence", "speed") if re.search(rf"\b{t}\b", low)]
    if types:
        out["type"] = "+".join(types)
    mm = re.search(r"(\d{1,2})\s*magnet", low)
    if mm:
        out["magnets"] = int(mm.group(1))
    out["details"] = _clean(v)
    return out


def _pedal_assist(v, brand):
    out = {}
    ml = re.search(r"(\d{1,2})\s*(?:levels?|pas\b|modes?)", v, re.I)
    if ml:
        out["levels"] = int(ml.group(1))
    out["boost"] = bool(re.search(r"boost", v, re.I))
    out["details"] = _clean(v)
    return out


def _chainring(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SHIFTING + ("Prowheel", "Lasco"), brand))
    if man:
        out["manufacturer"] = man
    mt = re.search(r"(\d{2})\s*t\b", v, re.I)
    if mt:
        out["teeth"] = int(mt.group(1))
        rest = re.sub(r"\d{2}\s*t\b", " ", rest, count=1, flags=re.I)
    out["narrow_wide"] = bool(re.search(r"narrow.?wide", v, re.I))
    out["details"] = _clean(rest)
    return out


def _pedals(v, brand):
    rest, low = v, v.lower()
    out = {}
    mt = re.search(r"(9/16|1/2)\s*\"?", v)
    if mt:
        out["thread"] = mt.group(1) + '"'
        rest = rest.replace(mt.group(0), " ", 1)
    if "carbon" in low:
        out["material"] = "carbon"
    elif re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    elif re.search(r"composite|nylon|plastic|resin", low):
        out["material"] = "composite"
    if "fold" in low:
        out["type"] = "folding"
    elif "platform" in low:
        out["type"] = "platform"
    out["details"] = _clean(rest)
    return out


def _spokes(v, brand):
    out, low = {}, v.lower()
    mg = re.search(r"(\d{1,2})\s*g\b", v, re.I)
    if mg:
        out["gauge"] = int(mg.group(1))
    if "stainless" in low:
        out["material"] = "stainless"
    elif re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    out["details"] = _clean(v)
    return out


def _saddle(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(SADDLES, brand))
    if man:
        out["manufacturer"] = man
    mw = re.search(r"(\d{2,3})\s*mm\s*(?:wide|width)", v, re.I)
    if mw:
        out["width_mm"] = int(mw.group(1))
        rest = re.sub(r"\d{2,3}\s*mm\s*(?:wide|width)", " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _seat_binder(v, brand):
    rest, low = v, v.lower()
    out = {}
    md = re.search(r"(\d{2}(?:\.\d)?)\s*mm", v)
    if md:
        out["diameter_mm"] = float(md.group(1))
        rest = re.sub(r"\d{2}(?:\.\d)?\s*mm", " ", rest, count=1)
    if re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    if re.search(r"quick.?release|\bqr\b", low):
        out["type"] = "quick_release"
    elif "bolt" in low:
        out["type"] = "bolt"
    out["details"] = _clean(rest)
    return out


def _tubes(v, brand):
    out, low = {}, v.lower()
    if "presta" in low:
        out["valve"] = "presta"
    elif "schrader" in low:
        out["valve"] = "schrader"
    mv = re.search(r"(\d{2})\s*mm\s*valve", low)
    if mv:
        out["valve_mm"] = int(mv.group(1))
    out["details"] = _clean(v)
    return out


def _frame(v, brand):
    out, low = {}, v.lower()
    if "carbon" in low:
        out["material"] = "carbon"
    elif re.search(r"6061|6063|alumin|alloy", low):
        out["material"] = "aluminum"
    elif re.search(r"cro-?mo|chromoly|steel", low):
        out["material"] = "steel"
    elif "magnesium" in low:
        out["material"] = "magnesium"
    out["integrated_battery"] = bool(re.search(r"intern(al)? battery|integrated battery|in[\s-]?frame batter", low))
    out["folding"] = bool(re.search(r"fold", low))
    out["details"] = _clean(v)
    return out


def _rims(v, brand):
    out, low = {}, v.lower()
    if re.search(r"alloy|alumin", low):
        out["material"] = "aluminum"
    elif "steel" in low:
        out["material"] = "steel"
    out["double_wall"] = bool(re.search(r"double.?wall", low))
    ms = re.search(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|in\b|inch)", low)
    if ms:
        out["size_in"] = float(ms.group(1))
    out["details"] = _clean(v)
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
    if f == "pedal_assist":
        return _pedal_assist
    if "derailleur" in f or "shifter" in f or "shift_lever" in f or f == "e_shifter":
        return _derailleur
    if "cassette" in f or "freewheel" in f:
        return _cassette
    if f == "chain":
        return _chain
    if f.startswith("chainring"):
        return _chainring
    if "crank" in f:
        return _crankset
    if "fork" in f or f == "suspension":
        return _fork
    if "shock" in f or f == "rear_suspension":
        return _shock
    if "brake" in f and "rotor" not in f:
        return _brake
    if "charger" in f:
        return _charger
    if "controller" in f:
        return _controller
    if "sensor" in f:
        return _sensor
    if "motor" in f or f == "drive_unit":
        return _motor
    if f == "battery":
        return _battery
    if "tire" in f or "tyre" in f:
        return _tire
    if "tube" in f:
        return _tubes
    if "display" in f:
        return _display
    if f == "stem":
        return _stem
    if f in ("seatpost", "seat_post"):
        return _seatpost
    if "handlebar" in f:
        return _handlebars
    if f == "saddle":
        return _saddle
    if "binder" in f:
        return _seat_binder
    if f in ("pedals", "pedal"):
        return _pedals
    if "spoke" in f:
        return _spokes
    if f in ("rims", "rim"):
        return _rims
    if f == "frame":
        return _frame
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
