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
          "Nutt", "Promax", "Logan", "Dorado", "Juin Tech", "Clarks", "Apse",
          "Star Union", "Star-Union")

# Brake series that are hydraulic disc even when the spec omits "hydraulic": the
# SRAM disc-brake line (DB/Maven/Code/Guide/Level/G2/RED E1), Shimano's hydraulic
# groups, Magura MT, TRP/Trickstuff, and Tektro's HD-/named hydraulic calipers.
# The leading alternation also tolerates the common "hydralic"/"hyrdaulic" typos.
_HYDRAULIC_BRAKE = re.compile(
    r"hydr\w{0,3}lic|hyrd\w{0,3}lic"
    r"|\bDB\s?\d|\bDB\b|\bMaven\b|\bCode\b|\bGuide\b|\bLevel\b|\bG2\b|RED\s*E1"
    r"|\bMT[-\s]?\d|deore|\bSLX\b|\bXT\b|\bXTR\b|\bCUES\b|\bGRX\b|\bRX\d{3}"
    r"|DH-?R|Trickstuff|Quadiem|\bSlate\b"
    r"|\bHD[-\s]?[A-Z]?\d|Orion|Auriga|Gemini|Juin",
    re.I)

# Mechanical (cable-actuated) disc brake signals, incl. Tektro's MD- series.
_MECHANICAL_BRAKE = re.compile(r"mechanical|cable|\bMD[-\s]?[A-Z]?\d", re.I)
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


# Tokens that end a model name (spec descriptors, materials, component nouns,
# connectors) — used to pull the model/series out of the leftover after the
# manufacturer (e.g. "SRAM Apex Hydraulic Disc 160mm" -> model "Apex").
_MODEL_STOP = {
    "hydraulic", "mechanical", "cable", "disc", "rim", "air", "coil", "spring",
    "rigid", "suspension", "sealed", "alloy", "aluminum", "aluminium", "carbon",
    "steel", "composite", "nylon", "plastic", "resin", "removable", "internal",
    "integrated", "lithium-ion", "lithium", "tubeless", "double-wall", "double",
    "wall", "thru-axle", "nutted", "schrader", "presta", "ergonomic", "lock-on",
    "lock", "platform", "folding", "dropper", "telescoping", "threadless", "quill",
    "riser", "flat", "bmx", "cruiser", "narrow", "wide", "adjustable", "forged",
    "custom", "tuned", "comfort", "premium", "standard", "front", "rear", "dual",
    "single", "with", "and", "the", "for", "by", "or", "of", "w/",
    "saddle", "seatpost", "seat", "post", "stem", "handlebar", "handlebars",
    "grip", "grips", "fork", "shock", "motor", "battery", "cell", "cells", "brake",
    "brakes", "lever", "levers", "rotor", "rotors", "chain", "cassette",
    "freewheel", "derailleur", "shifter", "crank", "crankset", "chainring",
    "chainrings", "pedal", "pedals", "wheel", "wheels", "tire", "tires", "rims",
    "spoke", "spokes", "hub", "controller", "charger", "display", "throttle",
    "sensor", "headset", "binder", "kickstand", "rack", "fender", "fenders",
    "light", "bell", "bracket", "bottom", "drive",
}


def _leading_model(text: str) -> str:
    """The model/series name at the start of a leftover string (up to 4 tokens),
    stopping at a number, unit, or spec/component word."""
    out = []
    for tok in text.split():
        t = tok.strip(",.;:()/\"'")
        tl = t.lower()
        if not t or tl in _MODEL_STOP:
            break
        if re.match(r"^[\d.]+$", t) or re.match(
                r"^\d+(\.\d+)?(mm|cm|w|v|ah|wh|kwh|nm|t|g|h|lux|lm|°|%|in|\")$", tl):
            break
        out.append(t)
        if len(out) >= 4:
            break
    return " ".join(out).strip(" ,.-/")


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


# ------------------------ shared field extractors ------------------------
# Sub-logic shared by several component parsers, centralized so a fix lands in
# every parser at once instead of in N copy-pasted blocks.

# Material classification, in global priority order. The key correctness point:
# "carbon" means carbon *fiber*; a "(high) carbon steel" alloy is STEEL — the
# negative lookahead keeps the carbon rule from firing on it (the bug that made
# VIVI's "High Carbon Steel" frame read as a carbon-fiber frame).
_MATERIAL_RULES = [
    ("carbon",    r"carbon(?![\s-]*steel)"),
    ("stainless", r"stainless"),
    ("aluminum",  r"6061|6063|alumin|alloy"),
    ("steel",     r"cro-?mo|chromoly|\bsteel\b"),
    ("magnesium", r"magnesium"),
    ("composite", r"composite|nylon|plastic|resin"),
    ("leather",   r"leather"),
    ("rubber",    r"rubber"),
    ("foam",      r"foam"),
]


def material(text: str, *allowed: str) -> str | None:
    """First material (in global priority order) whose pattern matches `text`, limited
    to the `allowed` vocabulary the calling parser recognizes, e.g.
    `material(low, "carbon", "aluminum", "steel")`. Returns None when nothing matches
    (callers only set out["material"] on a hit, preserving "omit when unknown")."""
    low = text.lower()
    for name, pat in _MATERIAL_RULES:
        if name in allowed and re.search(pat, low):
            return name
    return None


def voltage_v(text: str) -> int | None:
    """System voltage like "48V" — shared by the motor and battery parsers."""
    m = re.search(r"(\d{2,3})\s*v\b", text, re.I)
    return int(m.group(1)) if m else None


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


_PISTON_WORD = {"single": 1, "one": 1, "dual": 2, "twin": 2, "two": 2,
                "triple": 3, "three": 3, "quad": 4, "four": 4, "six": 6}


def _brake(v, brand, rotor_text=""):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(BRAKES, brand))
    if man:
        out["manufacturer"] = man
        # Model = the code-bearing token(s) right after the manufacturer, e.g.
        # "Star Union Talon P4" -> "Talon P4", "Tektro HD-T535" -> "HD-T535". Require
        # a digit or an all-caps hyphenated code so descriptors ("Hydraulic Disc")
        # are not mistaken for a model.
        mm = re.search(re.escape(man) + r"\s+([A-Z][\w.\-]*(?:[\s,]+[A-Z][\w.\-]*){0,2})", v)
        if mm:
            cand = mm.group(1).strip().rstrip(".,;")
            if re.search(r"\d|[A-Z]{2,}-", cand):
                out["model"] = cand
                rest = rest.replace(cand, "", 1)
    low = v.lower()
    if _HYDRAULIC_BRAKE.search(v):
        out["actuation"] = "hydraulic"
    elif _MECHANICAL_BRAKE.search(v):
        out["actuation"] = "mechanical"
    if "disc" in low:
        out["kind"] = "disc"
    elif re.search(r"\brim\b|\bv-?brake", low):
        out["kind"] = "rim"
    # piston count: digit ("4-piston") or word ("quad-/dual-/single-piston").
    m, rest = _consume(rest, r"(\d)\s*[-\s]?piston")
    if m:
        out["pistons"] = int(m.group(1))
    else:
        mw = re.search(r"\b(single|one|dual|twin|two|triple|three|quad|four|six)"
                       r"[-\s]?piston", rest, re.I)
        if mw:
            out["pistons"] = _PISTON_WORD[mw.group(1).lower()]
            rest = re.sub(r"\b(?:single|one|dual|twin|two|triple|three|quad|four|six)"
                          r"[-\s]?piston", "", rest, count=1, flags=re.I)
    blob = v + " " + (rotor_text or "")
    md = re.search(r"(\d{3})\s*mm", blob)            # rotor diameter (160/180/203)
    if md:
        out["rotor_mm"] = int(md.group(1))
        rest = re.sub(r"\d{3}\s*mm", "", rest, count=1)
    mt = re.search(r"(\d(?:\.\d)?)\s*mm\s*(?:thick|thickness)|x\s*(\d(?:\.\d)?)\s*mm", blob, re.I)
    if mt:
        out["rotor_thickness_mm"] = float(mt.group(1) or mt.group(2))
    # Many vendors list only the brake model ("SRAM DB8 Stealth 200mm", "Tektro
    # Orion HD-M745 Quad-Piston"); infer the disc/hydraulic kind they omit so it
    # doesn't read as a rim brake downstream. A rotor, a piston caliper, or a
    # known hydraulic series each implies a disc brake.
    blob_l = (v + " " + (rotor_text or "")).lower()
    if "kind" not in out and (out.get("rotor_mm") or out.get("pistons")
                              or "piston" in blob_l or _HYDRAULIC_BRAKE.search(v)):
        out["kind"] = "disc"
    if out.get("kind") == "disc" and "actuation" not in out:
        # hydraulic when a known hydraulic series or a (multi-)piston caliper —
        # mechanical disc brakes don't advertise piston counts
        if (_HYDRAULIC_BRAKE.search(v) or "piston" in blob_l
                or (out.get("pistons") or 0) >= 2):
            out["actuation"] = "hydraulic"
    out["details"] = _clean(rest)
    return out


def _motor(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(MOTORS, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    # A "boost mode" wattage is the in-boost peak the brand advertises (Aventon:
    # "750W (1440W in Boost Mode)"). Capture it as a peak fallback, then drop the
    # boost parenthetical so it can't read as the continuous rating. An explicit
    # "Peak <n>W" below still wins. (The torque-in-boost figure is left dropped.)
    bm = (re.search(r"(\d{3,4})\s*w[^)0-9]{0,12}boost", low)
          or re.search(r"boost[^)0-9]{0,15}(\d{3,4})\s*w", low))
    boost_w = int(bm.group(1)) if bm else None
    low = re.sub(r"\([^)]*boost[^)]*\)", " ", low)
    if re.search(r"mid[\s-]?drive|mid[\s-]?motor", low):
        out["placement"] = "mid"
    elif re.search(r"\bhub\b", low):
        out["placement"] = "hub"
    # Peak first. "Peak <n>W" ("Rated 750W, Peak 1200W") binds tighter than
    # "<n>W ... Peak" ("1188W Peak"), and neither gap may cross another number
    # ("750W (1188W Peak)" peaks at 1188), a comma/paren ("1000W Peak, Rated
    # 500W" must not read 500), or a slash ("1764W Peak Hub Motor / 750W
    # Nominal" peaks at 1764, not the post-slash 750).
    mp = (re.search(r"peak[^0-9,()/]{0,14}(\d{3,4})\s*w", low)
          or re.search(r"(\d{3,4})\s*w[^.\d]{0,14}peak", low))
    if mp:
        out["peak_w"] = int(mp.group(1))
        cont = low[:mp.start()] + " " + low[mp.end():]
    else:
        cont = low
    m, _ = _consume(cont, r"(\d{3,4})\s*w\b")
    if m:
        out["power_w"] = int(m.group(1))
    # boost figure stands in as peak when the spec stated no explicit peak
    if boost_w and "peak_w" not in out:
        out["peak_w"] = boost_w
    m = re.search(r"(\d{2,3})\s*n[·.\s]?m", low)
    if m:
        out["torque_nm"] = int(m.group(1))
    volt = voltage_v(low)
    if volt is not None:
        out["voltage_v"] = volt
    # strip the matched numbers (and their orphaned qualifiers) from details
    for pat in (r"\([^)]*boost[^)]*\)",
                r"\d{3,4}\s*w\s*\(?\s*peak\)?", r"peak[^0-9]{0,14}\d{3,4}\s*w",
                r"\d{3,4}\s*w", r"\d{2,3}\s*n[·.\s]?m", r"\d{2,3}\s*v\b",
                r"\((?:sustained|continuous|nominal|rated|peak|max\.?\s*power|cont\.?)\)",
                r"\btorque\b",
                # placement words are already shown in the Drive column — drop
                # them (and the bare "motor"/"drive") so Extra isn't redundant
                r"mid[\s-]?drive", r"\bhub\b", r"\bdrive\b", r"\bmotor\b"):
        rest = re.sub(pat, "", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


_BATT_NUMWORD = {"two": 2, "twin": 2, "double": 2, "three": 3, "triple": 3, "four": 4}
_BATT_WH_RE = r"(\d{3,4}(?:\.\d+)?)\s*wh"
# Phrases that mean a second/extra battery is OPTIONAL or capacity-capable, not
# shipped standard — so the bike's standard config is a single pack.
_BATT_OPTIONAL = re.compile(
    r"optional|\bready\b|capable|expandable|max(?:imum)?\s+capacity|up\s+to"
    r"|\bbay\b|version|\bver\.|range\s+extender|second\s+batter|additional\s+batter"
    r"|swappable", re.I)


def battery_pack_count(v: str) -> int:
    """How many battery packs the STANDARD config ships with (default 1). Recognises
    "dual", "(2) … batteries", "2x", "two/three/four … batteries"; returns 1 when the
    extra pack is qualified as optional/ready/version (e.g. Tern "optional 2 x 500 Wh",
    Heybike "Dual Battery Ver."). Used by both the normalized parser and the BOM
    estimator so a genuine standard dual (Monarc) is counted, but a dual-*capable*
    bike is not."""
    if _BATT_OPTIONAL.search(v):
        return 1
    if re.search(r"\bdual\b", v, re.I):
        return 2
    m = re.search(r"\b(two|twin|double|three|triple|four)\b", v, re.I)
    if m and re.search(r"batter", v, re.I):
        return _BATT_NUMWORD[m.group(1).lower()]
    m = re.search(r"\b([2-4])\s*[x×]\b", v, re.I)
    if m:
        return int(m.group(1))
    # "(N)" quantity prefix sitting just before a battery/lithium/cell word, e.g.
    # "(2) Lithium-ion … batteries" — anywhere in the (possibly concatenated) blob.
    m = re.search(r"\(([2-4])\)\s*(?:[\w.,-]+\s+){0,3}(?:lithium|li[-\s]?ion|batter|cell)",
                  v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([2-4])[)\s-]+(?:lithium|li[-\s]?ion|batter)", v, re.I)
    if m:
        return int(m.group(1))
    return 1


def battery_system_wh(v: str):
    """(per_pack_wh, total_wh, pack_count) for the standard config, or (None, None,
    count) when no Wh figure is present. An explicit "combined"/"total" Wh is used as
    the system total verbatim (it already sums the packs); otherwise the smallest Wh
    figure is the per-pack value and the total is per_pack × pack_count."""
    whs = [float(x) for x in re.findall(_BATT_WH_RE, v, re.I)]
    count = battery_pack_count(v)
    if not whs:
        return None, None, count
    per_pack = min(whs)
    if re.search(r"combined|total", v, re.I):
        total = max(whs)
    else:
        total = per_pack * count
    return per_pack, total, count


def _battery(v, brand):
    rest = v
    out = {}
    cell, _ = _find_brand(v, list(CELLS))
    if cell:
        out["cell_brand"] = cell
    man, rest = _find_brand(rest, _brands_for(("Bosch",), brand))
    if man:
        out["manufacturer"] = man
    # capacity_wh is the per-pack value; multi-pack bikes also expose pack_count and
    # the combined total_capacity_wh (see battery_system_wh for the standard-config
    # rules around optional/combined batteries).
    per_pack, total_wh, count = battery_system_wh(v)
    if per_pack is not None:
        out["capacity_wh"] = int(per_pack) if per_pack == int(per_pack) else round(per_pack, 1)
        if total_wh and total_wh != per_pack:
            out["pack_count"] = count
            out["total_capacity_wh"] = int(total_wh) if total_wh == int(total_wh) else round(total_wh, 1)
    volt = voltage_v(v)
    if volt is not None:
        out["voltage_v"] = volt
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*ah", v, re.I)
    if m:
        out["amphours_ah"] = float(m.group(1))
    m = re.search(r"\b(21700|18650|20700)\b", v)
    if m:
        out["cell_format"] = m.group(1)
    # Only assert removability when the source explicitly says so: an explicit
    # negation -> False; a bare "removable"/"detachable" -> True; silence (most
    # marketing blurbs) -> omit, so we never falsely claim a battery is fixed.
    # NB "integrated"/"internal" describe an in-frame battery, NOT a fixed one
    # ("integrated & removable", "Removable integrated downtube battery"), so they
    # are deliberately not treated as non-removable.
    if re.search(r"non[-\s]?removable|not\s+removable|non[-\s]?detachable"
                 r"|fixed\s+battery", v, re.I):
        out["removable"] = False
    elif re.search(r"removable|detachable", v, re.I):
        out["removable"] = True
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
    # wheel diameter x tire width, e.g. 26x4.0, 27.5 x 2.20, 29x2.4", 700x45c.
    # Split into separate diameter + width. The (?<!\d) stops the diameter being
    # taken out of a 3-digit number. 700-series are road/ISO (width in mm).
    m = re.search(r"(?<!\d)(\d{2,3}(?:\.\d)?)\s*[x×]\s*(\d{1,2}(?:\.\d+)?)\s*([c\"”]?)", rest)
    if m:
        dia, wid, suffix = float(m.group(1)), float(m.group(2)), m.group(3)
        if dia >= 100 or suffix.lower() == "c":          # road/ISO, e.g. 700c
            out["size"] = f"{int(dia)}c"
            out["width_mm"] = int(wid)
        else:                                            # inch sizing (20/26/27.5/29)
            out["diameter_in"] = dia
            out["width_in"] = wid
        rest = rest[:m.start()] + " " + rest[m.end():]
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
    mat = material(low, "carbon", "aluminum", "steel")
    if mat:
        out["material"] = mat
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
    mat = material(low, "carbon", "aluminum")
    if mat:
        out["material"] = mat
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
    mat = material(low, "carbon", "aluminum", "steel")
    if mat:
        out["material"] = mat
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
    mat = material(low, "carbon", "aluminum", "composite")
    if mat:
        out["material"] = mat
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
    mat = material(low, "stainless", "aluminum")
    if mat:
        out["material"] = mat
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
    mat = material(low, "aluminum")
    if mat:
        out["material"] = mat
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
    mat = material(low, "carbon", "aluminum", "steel", "magnesium")
    if mat:
        out["material"] = mat
    out["integrated_battery"] = bool(re.search(r"intern(al)? battery|integrated battery|in[\s-]?frame batter", low))
    out["folding"] = bool(re.search(r"fold", low))
    out["details"] = _clean(v)
    return out


def _rims(v, brand):
    out, low = {}, v.lower()
    mat = material(low, "aluminum", "steel")
    if mat:
        out["material"] = mat
    out["double_wall"] = bool(re.search(r"double.?wall", low))
    ms = re.search(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|in\b|inch)", low)
    if ms:
        out["size_in"] = float(ms.group(1))
    out["details"] = _clean(v)
    return out


def _bottom_bracket(v, brand):
    out, low = {}, v.lower()
    if re.search(r"square[\s-]?taper", low):
        out["type"] = "square_taper"
    elif "isis" in low:
        out["type"] = "isis"
    elif re.search(r"press[\s-]?fit", low):
        out["type"] = "press_fit"
    elif "cartridge" in low:
        out["type"] = "cartridge"
    elif "thread" in low:
        out["type"] = "threaded"
    out["sealed"] = "sealed" in low
    out["torque_sensor"] = bool(re.search(r"torque sensor", low))
    mw = re.search(r"(\d{2,3})\s*mm", low)
    if mw:
        out["width_mm"] = int(mw.group(1))
    out["details"] = _clean(v)
    return out


def _throttle(v, brand):
    rest, low = v, v.lower()
    out = {}
    man, rest = _find_brand(rest, _brands_for((), brand))
    if man:
        out["manufacturer"] = man
    if re.search(r"half[\s-]?twist", low):
        out["type"] = "half_twist"
    elif "twist" in low:
        out["type"] = "twist"
    elif "thumb" in low:
        out["type"] = "thumb"
    if re.search(r"\bleft\b|\blh\b", low):
        out["side"] = "left"
    elif re.search(r"\bright\b|\brh\b", low):
        out["side"] = "right"
    out["details"] = _clean(rest)
    return out


def _grips(v, brand):
    rest, low = v, v.lower()
    out = {}
    man, rest = _find_brand(rest, _brands_for(("Ergon", "Velo"), brand))
    if man:
        out["manufacturer"] = man
    out["lock_on"] = bool(re.search(r"lock[\s-]?on|locking|lockable", low))
    out["ergonomic"] = "ergonomic" in low
    mat = material(low, "leather", "rubber", "foam")
    if mat:
        out["material"] = mat
    out["details"] = _clean(rest)
    return out


def _light(v, brand):
    out, low = {}, v.lower()
    # lumens = total light output (the light's "power"); capture it robustly.
    mlm = re.search(r"(\d{2,4})\s*[-]?\s*(?:lm\b|lumens?)", low)
    if mlm:
        out["lumens"] = int(mlm.group(1))
    ml = re.search(r"(\d{2,4})\s*lux", low)
    if ml:
        out["lux"] = int(ml.group(1))
    out["brake_light"] = bool(re.search(r"brake\s*(?:signal|light)|braking\s*indicator", low))
    out["turn_signal"] = bool(re.search(r"turn\s*signal|blinker", low))
    # A horn is a separate safety item, not a property of the light — group_specs
    # surfaces it as its own `horn` field under Safety, so it is not parsed here.
    out["integrated"] = "integrated" in low
    rest = re.sub(r"\d{2,4}\s*lux|\d{2,4}\s*[-]?\s*(?:lm\b|lumens?)", " ", v, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _wheel(v, brand):
    rest, low = v, v.lower()
    out = {}
    ms = re.search(r"\b(\d{2}(?:\.\d)?)\s*(?:\"|in\b|inch)", low)
    if ms:
        out["size_in"] = float(ms.group(1))
    mh = re.search(r"(\d{2})\s*(?:hole|h\b)", low)
    if mh:
        out["holes"] = int(mh.group(1))
    mg = re.search(r"(\d{2})\s*g\b", low)
    if mg:
        out["gauge"] = int(mg.group(1))
    if re.search(r"thru[\s-]?axle", low):
        out["axle"] = "thru"
    elif "nutted" in low:
        out["axle"] = "nutted"
    elif re.search(r"quick[\s-]?release|\bqr\b", low):
        out["axle"] = "quick_release"
    if "presta" in low:
        out["valve"] = "presta"
    elif "schrader" in low:
        out["valve"] = "schrader"
    out["double_wall"] = bool(re.search(r"double.?wall", low))
    out["tubeless"] = "tubeless" in low
    mat = material(low, "aluminum")
    if mat:
        out["material"] = mat
    for pat in (r"\d{2}(?:\.\d)?\s*(?:\"|in\b|inch)", r"\d{2}\s*(?:hole|h\b)", r"\d{2}\s*g\b",
                r"\d{1,2}x\d{2,3}\s*mm?", r"thru[\s-]?axle|nutted\s*axle|quick[\s-]?release",
                r"presta|schrader", r"double.?wall", r"tubeless(?:\s*(?:ready|compatible))?",
                r"\bvalve\b", r"alumin\w*|alloy", r"fat\s*tire\s*rim|\brim\b"):
        rest = re.sub(pat, " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _cert(v, brand):
    out = {}
    stds = re.findall(r"\bUL\s*\d{3,4}\b|\bEN\s*\d{4,5}\b|\bISO\s*\d{3,5}\b|\bIEC\s*\d{4,5}\b", v, re.I)
    if stds:
        out["standards"] = list(dict.fromkeys(re.sub(r"\s+", " ", s).upper() for s in stds))
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
    m = re.search(r'(\d(?:\.\d)?)\s*(?:inch(?:es)?|["”])', v)
    if m:
        out["size_in"] = float(m.group(1))
        rest = re.sub(r'\d(?:\.\d)?\s*(?:inch(?:es)?|["”])', " ", rest)
    if "bluetooth" in low:
        out["bluetooth"] = True
        rest = re.sub(r"bluetooth", " ", rest, flags=re.I)
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
    if "bottom_bracket" in f:
        return _bottom_bracket
    if "throttle" in f:
        return _throttle
    if "grip" in f:
        return _grips
    if "light" in f:
        return _light
    if f.endswith("_wheel") or f in ("wheel", "wheels"):
        return _wheel
    if "certif" in f or "compliance" in f or f == "iso_standard":
        return _cert
    return None


# ------------------------- unitized scalar measurements -------------------------
# Standalone measurement fields (not components) -> a bare number with the unit in
# the field name. The four rider-facing "toggle-able" dimensions (length/geometry,
# speed, weight, range) are emitted in BOTH units (e.g. weight_lb + weight_kg): the
# unit(s) present in the source are parsed natively and the missing counterpart is
# converted here, at build time, so the site can render either mode with no math.
# Torque (_nm) and power (_w) are pinned to their standard unit (no imperial dual).

def _maxnum(v, pat):
    vals = [float(m.group(1)) for m in re.finditer(pat, v, re.I)]
    return max(vals) if vals else None


def _n1(x):
    """Round to 1 decimal, dropping a trailing .0 (so 62.0 -> 62, 28.06 -> 28.1)."""
    x = round(x, 1)
    return int(x) if x == int(x) else x


def _key(field, suffix):
    return field if field.endswith(suffix) else field + suffix


# Per-unit number tokens. Inch/feet marks come straight and curly; handle both.
_RE_MPH = r"(\d+(?:\.\d+)?)\s*mph"
_RE_KPH = r"(\d+(?:\.\d+)?)\s*(?:km/?h|kph|kmh)"
_RE_LB = r"(\d+(?:\.\d+)?)\s*(?:lbs?|pounds?)\b"
_RE_KG = r"(\d+(?:\.\d+)?)\s*kg"
_RE_MI = r"(\d{2,3})\s*(?:miles?|mi\b)"
_RE_KM = r"(\d{2,3})\s*(?:km\b|kilometers?)"
_RE_IN = r'(\d+(?:\.\d+)?)\s*(?:in\b|inch(?:es)?|["”])'
_RE_MM = r"(\d+(?:\.\d+)?)\s*mm"
_RE_CM = r"(\d+(?:\.\d+)?)\s*cm"

# Length values we can't reduce to one scalar -> leave as the original string:
# multi-size ("S2: …|S3: …"), L×W×H composites, feet-inch ranges.
_LEN_SKIP = re.compile(r"""[|×*]|['’]|\bx\b|["”]\s*[lwh]\b""", re.I)

# Geometry/length fields to dual-unitize (components are handled by parse_component
# first, so they never reach here and stay metric).
_LEN_KEYS = ("wheelbase", "reach", "stack", "standover", "stand_over",
             "step_over", "chainstay", "chain_stay", "head_tube", "seat_tube",
             "top_tube", "rider_height", "total_length", "handlebar_height",
             "handlebar_width")


def _speed(field, v):
    mph, kph = _maxnum(v, _RE_MPH), _maxnum(v, _RE_KPH)
    if mph is None and kph is None:
        return None
    if mph is None:
        mph = kph * 0.621371
    if kph is None:
        kph = mph * 1.60934
    return {_key(field, "_mph"): round(mph), _key(field, "_kph"): round(kph)}


def _weight(field, v):
    lb, kg = _maxnum(v, _RE_LB), _maxnum(v, _RE_KG)
    if lb is None and kg is None:
        return None
    if lb is None:
        lb = kg * 2.20462
    if kg is None:
        kg = lb / 2.20462
    return {_key(field, "_lb"): _n1(lb), _key(field, "_kg"): _n1(kg)}


def _range(field, v):
    mi, km = _maxnum(v, _RE_MI), _maxnum(v, _RE_KM)
    if mi is None and km is None:
        return None
    if mi is None:
        mi = km * 0.621371
    if km is None:
        km = mi * 1.60934
    return {_key(field, "_mi"): round(mi), _key(field, "_km"): round(km)}


def _length(field, v):
    if _LEN_SKIP.search(v):
        return None
    inch, mm, cm = _maxnum(v, _RE_IN), _maxnum(v, _RE_MM), _maxnum(v, _RE_CM)
    if mm is None and cm is not None:
        mm = cm * 10                      # cm -> mm is exact, stays metric
    if inch is None and mm is None:
        return None
    if inch is None:
        inch = mm / 25.4
    if mm is None:
        mm = inch * 25.4
    return {_key(field, "_in"): _n1(inch), _key(field, "_mm"): round(mm)}


def _u_nm(v):
    m = re.search(r"(\d+(?:\.\d+)?)\s*n[·.\s]?m", v, re.I)
    return round(float(m.group(1))) if m else None


def _u_w(v):
    m = re.search(r"(\d{2,4})\s*w\b", v, re.I)
    return int(m.group(1)) if m else None


def _dethousand(s: str) -> str:
    """Strip thousands separators so "1,200W" reads 1200, not 200."""
    return re.sub(r"(?<=\d),(?=\d{3})", "", s)


def unitize(field: str, value):
    """A dict {suffixed_field: number} for a recognized standalone measurement, else
    None. Toggle-able dimensions (length/speed/weight/range) emit BOTH units (native
    value parsed, counterpart converted at build time); torque/power emit their one
    pinned unit. Returns None when the field matches but no number parses (e.g.
    weight_size 'One Size') so the original string is kept untouched."""
    if not isinstance(value, str):
        return None
    value = _dethousand(value)
    f = field.lower()

    if "speed" in f and "speeds" not in f and "gear" not in f:
        return _speed(f, value)
    if any(t in f for t in ("weight", "payload", "load", "capacity")) and "size" not in f:
        return _weight(f, value)
    if "range" in f and "height" not in f and "speed" not in f and "adjustable" not in f:
        return _range(f, value)
    if "torque" in f:
        n = _u_nm(value)
        return {_key(f, "_nm"): n} if n is not None else None
    if ("power" in f or "wattage" in f) and "speed" not in f:
        n = _u_w(value)
        return {_key(f, "_w"): n} if n is not None else None
    if "angle" not in f and any(k in f for k in _LEN_KEYS):
        return _length(f, value)
    return None


def parse_component(field: str, value, brand: str | None = None,
                    siblings: dict | None = None):
    """Structured dict for a known component field, else None. `siblings` lets the
    brake parser borrow a separate rotor field for diameter/thickness."""
    fn = _resolver(field)
    if fn is None or not isinstance(value, str) or not value.strip():
        return None
    value = _dethousand(value)   # "1,200W" must parse as 1200, not 200
    if fn is _brake:
        rotor = ""
        for k, sv in (siblings or {}).items():
            if "rotor" in k and isinstance(sv, str):
                rotor += " " + sv
        result = _brake(value, brand, rotor)
    else:
        result = fn(value, brand)
    # When a manufacturer was found, pull the model/series out of the leftover
    # (e.g. "SRAM Apex Hydraulic Disc 160mm" -> manufacturer SRAM, model "Apex").
    if result and result.get("manufacturer") and not result.get("model"):
        mdl = _leading_model(result.get("details", ""))
        if mdl:
            det = result["details"]
            result["model"] = mdl
            tail = det[len(mdl):] if det[:len(mdl)].lower() == mdl.lower() else det.replace(mdl, "", 1)
            result["details"] = _clean(tail)
    # Stamp the canonical component kind (the parser's name) so the UI can pick
    # the right feature columns without re-deriving the type from noisy labels.
    if result:
        result["_kind"] = fn.__name__.lstrip("_")
    return result
