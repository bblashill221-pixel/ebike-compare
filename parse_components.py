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
          "TranzX", "Ultro", "Globe", "Shimano", "Fazua", "TQ")
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
    """Category brands + the bike's own/house brand, longest first. Dedupe is
    case-insensitive keeping the tuple's first spelling (the canonical one),
    and the sort is stable -- set() here made equal-length ties depend on hash
    randomization, flipping e.g. microSHIFT/MicroShift between runs."""
    cand = list(brands)
    if brand:
        cand += list(HOUSE.get(brand, ())) + [brand.title()]
    seen, ordered = set(), []
    for b in cand:
        if b.lower() not in seen:
            seen.add(b.lower())
            ordered.append(b)
    return sorted(ordered, key=lambda b: -len(b))


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
    # carbon = carbon *fibre* only. "carbon steel"/"high|low|mid|mild carbon" are
    # steel; a "carbon drive/belt" is a drivetrain. The lookbehinds drop the steel
    # qualifiers, the lookahead drops "carbon steel/drive/belt". (aluminum stays
    # ahead of steel so a named alloy wins.)
    ("carbon",    r"(?<!high )(?<!high-)(?<!low )(?<!low-)(?<!mid )(?<!mid-)"
                  r"(?<!medium )(?<!medium-)(?<!mild )(?<!mild-)carbon(?![\s-]*(?:steel|drive|belt))"),
    ("stainless", r"stainless"),
    ("aluminum",  r"6061|6063|7005|\ba3\d{2}\b|\ba380\b|alumin|alloy"),
    ("steel",     r"carbon[\s-]*steel|(?:high|low|mid|medium|mild)[\s-]*carbon|\bq\d{3}\b|cro-?mo|chromoly|\bsteel\b"),
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
            # keep "Aluminum Alloy" together as one material (like a 6061 grade) instead of
            # collapsing to bare "aluminum"; a specific grade still wins (callers append it,
            # e.g. frame -> "Aluminum 6061"), so only do this when no numbered grade is present
            if (name == "aluminum" and re.search(r"\balloy\b", low)
                    and not re.search(r"\b(6061|6063|7005|7046|a3\d{2}|a380)\b", low)):
                return "aluminum alloy"
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
    elif re.search(r"\bcoil\b|\bspring\b", low):
        out["type"] = "coil"
    # NB: "hydraulic"/"suspension"/"lockout"/"mechanical" describe damping/features, NOT
    # the spring, so they no longer imply a coil spring -- asserting "coil" on a "Hydraulic
    # Suspension Fork" conflicts with its own name (Vanpowers UrbanGlide). Such forks are
    # left with no `type` (still a suspension fork via travel/lockout below).
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
    mat = material(low, "carbon", "aluminum", "steel", "magnesium")
    if mat:
        out["material"] = mat
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
    mt = re.search(r"(\d{2,3})\s*mm\s*(?:of\s+)?(?:rear\s+)?(?:wheel\s+)?travel", rest, re.I)
    if mt:
        out["travel_mm"] = int(mt.group(1))
        rest = rest.replace(mt.group(0), " ", 1)
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
            # A piston descriptor ("Quad-Piston", "4-Piston") is a caliper attribute,
            # not part of the model — strip it so it falls through to the piston parse
            # below (and "Orion HD-M745 Quad-Piston" normalizes to "Orion HD-M745").
            cand = re.sub(r"[\s,]*(?:\d|single|one|dual|twin|two|triple|three|quad"
                          r"|four|six)[-\s]*piston\b.*$", "", cand, flags=re.I).strip()
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
    # piston count: digit ("4-piston") or word ("quad-/dual-/single-piston"). The
    # separator is [-\s]* so spacing variants all read the same ("4-piston",
    # "4 piston", "4- Piston").
    m, rest = _consume(rest, r"(\d)\s*[-\s]*piston")
    if m:
        out["pistons"] = int(m.group(1))
    else:
        mw = re.search(r"\b(single|one|dual|twin|two|triple|three|quad|four|six)"
                       r"[-\s]*piston", rest, re.I)
        if mw:
            out["pistons"] = _PISTON_WORD[mw.group(1).lower()]
            rest = re.sub(r"\b(?:single|one|dual|twin|two|triple|three|quad|four|six)"
                          r"[-\s]*piston", "", rest, count=1, flags=re.I)
    blob = v + " " + (rotor_text or "")
    # Combined "diameter × thickness" written with any of *, x, × ("160*1.8mm",
    # "203x2mm", "180 × 1.9 mm") — capture both in one pass.
    mc = re.search(r"(\d{3})\s*[*x×]\s*(\d(?:\.\d)?)\s*mm", blob, re.I)
    if mc:
        out["rotor_mm"] = int(mc.group(1))
        out["rotor_thickness_mm"] = float(mc.group(2))
        rest = re.sub(r"\d{3}\s*[*x×]\s*\d(?:\.\d)?\s*mm", "", rest, count=1, flags=re.I)
    else:
        md = re.search(r"(\d{3})\s*mm", blob)        # rotor diameter (160/180/203)
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


# Bosch publishes a fixed torque per motor LINE and never states wattage (all units
# are 250W nominal). Many spec rows give only the line name ("Bosch Performance Line
# Speed, 250W") — so when the text doesn't state Nm, fill the known line torque.
# Most specific patterns first. An explicit Nm in the row always wins over this.
_BOSCH_TORQUE = [
    (re.compile(r"cargo line"), 85),
    (re.compile(r"performance line cx|performance cx"), 85),
    (re.compile(r"performance line speed|performance speed"), 85),
    (re.compile(r"performance line sprint|performance sprint"), 75),
    (re.compile(r"performance line"), 75),
    (re.compile(r"active line plus"), 50),
    (re.compile(r"active line"), 40),
]


def bosch_torque(text: str) -> int | None:
    """Known Bosch line torque (Nm) from a motor spec string; None if not a Bosch line."""
    if not re.search(r"\bbosch\b", text, re.I):
        return None
    low = text.lower()
    for rx, nm in _BOSCH_TORQUE:
        if rx.search(low):
            return nm
    return None


def _motor(v, brand):
    rest = v
    out = {}
    man, rest = _find_brand(rest, _brands_for(MOTORS, brand))
    if man:
        out["manufacturer"] = man
    low = v.lower()
    # A "boost mode" wattage is the bike's true peak -- the highest output a
    # shipped mode delivers (Aventon: "750W Peak (850W Peak in BOOST Mode)").
    # Capture it, then drop the boost parenthetical so it can't read as the
    # continuous rating; it's folded back in as peak_w below. (The
    # torque-in-boost figure is left dropped.)
    bm = (re.search(r"(\d{3,4})\s*w(?:att)?s?[^)0-9]{0,12}boost", low)
          or re.search(r"boost[^)0-9]{0,15}(\d{3,4})\s*w", low))
    boost_w = int(bm.group(1)) if bm else None
    # "850W Peak in BOOST Mode": the vendor calls the boost figure the peak,
    # so a "Peak"-labeled standard figure beside it is really the nominal
    # ("750W Peak (850W Peak in BOOST Mode)"). Without that wording ("1188W
    # Peak (1440W in Boost Mode)") the standard peak stays a peak.
    boost_is_peak = bool(re.search(r"\d\s*w(?:att)?s?\s*peak[^)0-9]{0,10}boost", low))
    low = re.sub(r"\([^)]*boost[^)]*\)", " ", low)
    # "Ultro" is Aventon's mid-drive family (Ultro S / Ultro X); their hub motors
    # are never named Ultro, and the trail rows ("Aventon Ultro X") often omit the
    # "mid-drive" word, so the model name alone settles placement.
    if re.search(r"mid[\s-]?drive|mid[\s-]?motor|\bultro\b", low):
        out["placement"] = "mid"
    elif re.search(r"\bhub\b", low):
        out["placement"] = "hub"
    elif man in ("Bosch", "Brose", "Specialized", "Shimano", "Yamaha", "TQ", "Fazua"):
        # these makers build only mid-drive e-bike motors, and their spec rows
        # rarely say so ("Bosch Performance Line CX")
        out["placement"] = "mid"
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
    m, _ = _consume(cont, r"(\d{3,4})\s*w(?:att)?s?\b")
    if m:
        out["power_w"] = int(m.group(1))
    # The boost figure is the true peak (highest shipped-mode output). When the
    # vendor's boost wording itself says "peak", the standard "Peak"-labeled
    # figure demotes to the nominal rating.
    if boost_w:
        explicit = out.get("peak_w")
        if boost_is_peak and explicit and explicit != boost_w and "power_w" not in out:
            out["power_w"] = explicit
        out["peak_w"] = max(boost_w, explicit or 0)
    m = re.search(r"(\d{2,3})\s*n[·.\s]?m", low)
    if m:
        out["torque_nm"] = int(m.group(1))
    # Bosch states torque per line, not in every row — fill the known line value
    # (and the 250W nominal) when the text didn't already give them.
    if man == "Bosch":
        if "torque_nm" not in out:
            t = bosch_torque(low)
            if t is not None:
                out["torque_nm"] = t
        out.setdefault("power_w", 250)
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
        ("Zoom", "Promax", "Kalloy", "UNO", "Satori", "Aerozine", "Brose",
         "RaceFace", "Race Face", "FSA", "Ritchey", "Truvativ", "Renthal"), brand))
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
        ("Zoom", "Promax", "Kalloy", "UNO", "Satori", "Aerozine",
         "RaceFace", "Race Face", "FSA", "Ritchey", "Truvativ", "Renthal"), brand))
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
                r"\d{1,3}\s*mm\s*rise", r"\brise\b\s*:?",
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
    man, rest = _find_brand(rest, _brands_for(
        ("Wellgo", "MKS", "RaceFace", "Race Face", "VP Components", "Crankbrothers",
         "Crank Brothers"), brand))
    if man:
        out["manufacturer"] = man
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
    """Clause-based: split the frame description on commas and classify each
    clause into a structured field; only unclassified clauses stay as details
    ("SmartForm C3 Alloy frame, low step-thru, removable downtube battery,
    semi-internal cable routing, tapered 1-1/8\"-1.5\" headtube, post mount
    disc, waterbottle and headtube rack mounts")."""
    out, low = {}, v.lower()
    mat = material(low, "carbon", "aluminum", "steel", "magnesium")
    # keep the aluminium alloy grade with the material so it reads "Aluminum 6061"
    grade = re.search(r"\b(6061|6063|7005|7046|a356|a380)\b", v, re.I)
    if mat == "aluminum" and grade:
        mat = f"aluminum {grade.group(1).upper()}"
    if mat:
        out["material"] = mat
    out["integrated_battery"] = bool(re.search(
        r"(?:intern\w*|integrated)[^,;]{0,24}batter"
        r"|(?:in[\s-]?(?:frame|tube)|down\s?tube)[^,;]{0,16}batter", low))
    out["folding"] = bool(re.search(r"fold", low))

    leftover = []
    for clause in re.split(r"\s*[,;]\s*", v):
        cl = clause.lower()
        if not cl.strip():
            continue
        if "batter" in cl:
            if re.search(r"removable", cl):
                out["removable_battery"] = True
            pos = re.search(r"down\s?tube|in[\s-]?tube|in[\s-]?frame|seat\s?tube|rear\s?rack", cl)
            if pos:
                out["battery_position"] = re.sub(r"[\s-]+", "_", pos.group(0))
            # strip just the battery phrase -- a comma-less description may
            # carry frame info in the same clause ("Gravity Cast 6061
            # Single-Butted Aluminum Alloy with Internal Battery")
            rem = re.sub(r"(?:removable|integrated|internal|external)?[\s]*"
                         r"(?:\d+\s*v\s*)?"
                         r"(?:down\s?tube|in[\s-]?tube|in[\s-]?frame|seat\s?tube|rear\s?rack)?"
                         r"[\s]*batter\w*", " ", clause, flags=re.I)
            rem = re.sub(r"\b(?:with|w/|featuring|and)\s*$", "", rem.strip(), flags=re.I)
            if re.search(r"[a-z0-9]", rem, re.I):
                leftover.append(rem)
            continue
        if re.search(r"cable|routing|cabling|wiring", cl):
            out["cable_routing"] = ("semi_internal" if re.search(r"semi", cl)
                                    else "external" if re.search(r"external", cl)
                                    else "internal" if re.search(r"intern|hidden|conceal", cl)
                                    else None) or out.get("cable_routing")
            if out.get("cable_routing"):
                continue
        if re.search(r"head\s?tube", cl) and re.search(r"tapered|\d", cl):
            ht = _clean(re.sub(r"head\s?tube", " ", clause, flags=re.I))
            if ht:
                out["headtube"] = ht
            continue
        if re.search(r"(post|flat|is)[\s-]?mount", cl):
            m = re.search(r"(post|flat|is)[\s-]?mount(\s+disc)?", cl)
            out["brake_mount"] = re.sub(r"[\s-]+", "_", m.group(0))
            continue
        if re.search(r"mounts?\b|bosses", cl):
            mounts = []
            for pat, name in ((r"water\s?bottle|bottle\s?cage", "water bottle"),
                              (r"\brack\b", "rack"), (r"fender", "fender"),
                              (r"kickstand", "kickstand"), (r"trailer", "trailer"),
                              (r"basket", "basket")):
                if re.search(pat, cl):
                    mounts.append(name)
            if mounts:
                out["mounts"] = sorted(set(mounts + (out.get("mounts") or [])))
                continue
        if re.search(r"step[\s-]?(thru|through)|low[\s-]?step|easy[\s-]?entry", cl):
            out["style"] = "step_thru"
            continue
        if re.search(r"step[\s-]?over|high[\s-]?step|mid[\s-]?step", cl):
            out["style"] = "step_over"
            continue
        # structured geometry clauses -> their own fields (keep them out of Details)
        m = re.search(r"(\d{2,3})\s*mm\s*(?:of\s*)?(?:rear\s*)?(?:wheel\s*)?travel", cl)
        if m:
            out["travel_mm"] = int(m.group(1))
            continue
        m = re.search(r"(\d{2,3})\s*mm\s*chain\s*line", cl)
        if m:
            out["chainline_mm"] = int(m.group(1))
            continue
        if re.search(r"thru[\s-]?axle|dropout|drop[\s-]?out", cl):
            ax = re.search(r"(\d{2,3})\s*[x×]\s*(\d{1,3})", cl)
            out["thru_axle"] = f"{ax.group(1)}x{ax.group(2)}mm" if ax else _clean(clause)
            continue
        m = re.fullmatch(r'\s*(\d{2}(?:\.\d)?)\s*(?:["”″\']|in(?:ch(?:es)?)?)\s*(?:wheels?)?\s*',
                         clause, re.I)
        if m:
            out["wheel_size_in"] = m.group(1)
            continue
        if re.search(r"kickstand", cl):
            out["mounts"] = sorted(set((out.get("mounts") or []) + ["kickstand"]))
            continue
        leftover.append(clause)
    det = ", ".join(leftover)
    if out["folding"]:
        det = re.sub(r"\bfold(?:ing|able)?\b", " ", det, flags=re.I)
    if grade:   # the grade now lives in `material`; don't repeat it in details
        det = re.sub(r"\b" + re.escape(grade.group(1)) + r"\b", " ", det, flags=re.I)
    out["details"] = _clean(det)
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
    man, rest = _find_brand(rest, _brands_for(
        ("Ergon", "Velo", "ODI", "Lizard Skins", "Wittkop", "SQlab", "Selle Royal",
         "Herrmans"), brand))
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
    rest, low = v, v.lower()
    out = {}
    man, rest = _find_brand(rest, _brands_for(
        ("Spanninga", "Herrmans", "Lezyne", "Roxim", "Supernova", "Busch & Müller",
         "Busch and Müller"), brand))
    if man:
        out["manufacturer"] = man
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
    rest = re.sub(r"\d{2,4}\s*lux|\d{2,4}\s*[-]?\s*(?:lm\b|lumens?)", " ", rest, flags=re.I)
    out["details"] = _clean(rest)
    return out


def _wheel(v, brand):
    rest, low = v, v.lower()
    out = {}
    man, rest = _find_brand(rest, _brands_for(
        ("DT Swiss", "Mavic", "Sun Ringle", "Sun Ringlé", "WTB", "Alex Rims",
         "Alexrims", "Jalco", "Rodi", "Novatec", "Mach1", "Formula"), brand))
    if man:
        out["manufacturer"] = man
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
    # Brakes and standalone rotor specs (Rotors, Brake Rotor, Front/Rear Rotor,
    # Disc Rotor) both go to _brake; the rotor's diameter/thickness merge into the
    # brake card downstream (SpecTable buckets same-kind instances by position).
    if "brake" in f or "rotor" in f:
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
    out = {_key(field, "_mph"): round(mph), _key(field, "_kph"): round(kph)}
    # Keep e-bike class info the unit extraction would otherwise discard:
    # explicit "Class 3" mentions in the value ("Speed: Class 3 electric bike,
    # with 28mph pedal assist"), or bare digit lists when the field itself is a
    # class row ("CLASS & SPEED: 1-3 & 28mph"). Lookarounds keep "28mph" out.
    m = re.search(r"class(?:es)?\s*[-:]?\s*([123](?:\s*(?:[/,&+]|or|and|to|-)\s*[123])*)",
                  str(v), re.I)
    if not m and "class" in str(field).lower():
        m = re.search(r"(?<!\d)([123](?:\s*[-/,&+]\s*[123])*)(?!\d)(?!\s*(?:mph|kph))",
                      str(v))
    if m:
        out["ebike_classes"] = m.group(1)
    return out


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


# A frame-size segment: "S/M:", "L/XL:", "Size S:", "M/L/XL :" — one or more
# size tokens (XS..XXL) joined by "/", optionally led by the word "Size", and
# terminated by a colon. The colon + token shape keeps this off ordinary text.
_SIZE_SEG = re.compile(r"(?:\bsize\s+)?\b((?:X{0,2}[SML])(?:\s*/\s*X{0,2}[SML])*)\s*:", re.I)


def _is_size_label(m: "re.Match") -> bool:
    # Only trust a match that's unambiguously a size: a multi-size group ("S/M")
    # or one explicitly introduced by "Size" — a bare "M:"/"L:" is too risky
    # (could be a left/right or other colon-delimited note).
    return "/" in m.group(1) or m.group(0).lstrip().lower().startswith("size")


def _split_by_size(value: str):
    """Split "common. S/M: …. L/XL: …" into (common_text, {SIZE: segment}), or
    None when fewer than two size segments are present."""
    matches = [m for m in _SIZE_SEG.finditer(value) if _is_size_label(m)]
    if len(matches) < 2:
        return None
    common = value[:matches[0].start()].strip(" .,;-")
    segs: dict[str, str] = {}
    for i, m in enumerate(matches):
        label = re.sub(r"\s*/\s*", "/", m.group(1).upper())
        end = matches[i + 1].start() if i + 1 < len(matches) else len(value)
        segs[label] = value[m.end():end].strip(" .,;-")
    return common, segs


def _parse_sized(fn, common: str, segs: dict, brand):
    """Parse each "common + per-size segment" with `fn`, then fold attributes that
    are identical across every size up to the top level and keep the rest in a
    `by_size` map keyed by the frame-size label."""
    per = {lbl: (fn(_dethousand(f"{common} {seg}".strip()), brand) or {})
           for lbl, seg in segs.items()}
    base = fn(_dethousand(common.strip()), brand) if common.strip() else {}
    keys = {k for d in per.values() for k in d if k != "details"}
    result: dict = {}
    by_size: dict[str, dict] = {lbl: {} for lbl in segs}
    for k in keys:
        vals = {lbl: per[lbl].get(k) for lbl in segs}
        present = [v for v in vals.values() if v is not None]
        if len(present) == len(segs) and all(v == present[0] for v in present):
            result[k] = present[0]                       # same on every size
        else:
            for lbl, v in vals.items():
                if v is not None:
                    by_size[lbl][k] = v
    if base.get("details"):
        result["details"] = base["details"]
    by_size = {lbl: a for lbl, a in by_size.items() if a}
    if by_size:
        result["by_size"] = by_size
    return result


# Unit spellings per structured-field suffix, so a parsed number's textual form
# ("180mm", "750 watts", '27.5"') can be located in the leftover details text.
_DETAIL_UNITS = [
    ("_wh", r"\s*wh\b"), ("_w", r"\s*w(?:att)?s?\b"), ("_nm", r"\s*n[·.\s]?m\b"),
    ("_v", r"\s*v(?:olts?)?\b"), ("_mm", r"\s*mm\b"), ("_cm", r"\s*cm\b"),
    ("_in", r"\s*(?:\"|''|in(?:ch(?:es)?)?\b)"), ("_lb", r"\s*(?:lbs?|pounds)\b"),
    ("_kg", r"\s*kgs?\b"), ("_deg", r"\s*(?:°|deg(?:rees?)?\b)"), ("_ah", r"\s*ah\b"),
]


def _strip_parsed_from_details(result: dict) -> None:
    """Remove every parsed-out value's textual form from `details`, so the UI's
    "Extra" column never repeats what the structured columns already show.
    Empty leftovers drop the key entirely (the UI hides absent columns)."""
    det = result.get("details")
    if not isinstance(det, str) or not det:
        if det == "":
            result.pop("details", None)
        return
    def strip_token(text: str, tok: str) -> str:
        # enum-ish tokens may be stored snake_case ("square_taper") and the page
        # may write compounds solid ("waterbottle") -- separators are optional
        pat = r"\b" + re.escape(tok).replace(r"\ ", r"[\s_-]*").replace("_", r"[\s_-]*") + r"\b"
        return re.sub(pat, " ", text, flags=re.I)

    for k, v in result.items():
        if k in ("details", "_kind", "by_size") or isinstance(v, bool) or v is None:
            continue
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and len(item) >= 3:
                    det = strip_token(det, item)
        elif isinstance(v, str) and len(v) >= 3:
            det = strip_token(det, v)
        elif isinstance(v, (int, float)):
            n = int(v) if float(v).is_integer() else v
            num = re.escape(str(n)) + (r"(?:\.0)?" if isinstance(n, int) else "")
            if k in ("speeds", "gears"):
                det = re.sub(rf"\b{num}[\s-]*speeds?\b", " ", det, flags=re.I)
                continue
            for suf, unit in _DETAIL_UNITS:
                if k.endswith(suf):
                    det = re.sub(rf"\b{num}{unit}", " ", det, flags=re.I)
                    break
    # orphaned unit tokens left behind by earlier per-parser stripping ("…, mm")
    det = re.sub(r"(?<![\w.])(?:mm|cm|wh|n[·.]?m|kgs?|lbs?)\b(?!\s*[\d])", " ", det, flags=re.I)
    # a dimensions connector whose numbers were both removed ("350mm x 31.6mm" -> "x")
    det = re.sub(r"(?<![0-9\"\w])x(?![0-9\w])", " ", det, flags=re.I)
    det = _clean(det)
    if re.search(r"[a-z0-9]", det, re.I):
        result["details"] = det
    else:
        result.pop("details", None)


# LLM-extracted component parses (llm_parse_components.py), keyed by
# sha256(kind|brand|text)[:20]. When the cache exists, it is the primary
# engine; the regex parsers below handle cache misses (new text between
# extraction runs), so the pipeline stays offline-safe.
try:
    import hashlib as _hashlib
    import json as _json
    from pathlib import Path as _Path
    _LLM_COMPONENTS = _json.loads(
        (_Path(__file__).parent / "data" / "curated" / "llm_components.json").read_text())
except (FileNotFoundError, ValueError):
    _LLM_COMPONENTS = {}


_ALUMINUM_RE = re.compile(r"6061|6063|7005|\ba3\d{2}\b|\ba380\b|alumin|\balloy\b", re.I)
_ALU_GRADE_RE = re.compile(r"\b(6061|6063|7005|7046|a3\d{2}|a380)\b", re.I)


def _canon_material(result):
    """Canonicalize aluminum alloys to "aluminum" so "Alloy"/"Aluminum alloy"/the
    LLM cache's "Aluminum" all group together — but KEEP an explicit alloy grade
    ("Aluminum 6061") when one is stated, so it displays as the full alloy name.
    The grade may be in the material string OR stranded in details (LLM parses
    keep it there); pull it onto the material and drop it from details."""
    if not (isinstance(result, dict) and isinstance(result.get("material"), str)
            and _ALUMINUM_RE.search(result["material"])):
        return result
    g = _ALU_GRADE_RE.search(result["material"])
    det = result.get("details")
    if not g and isinstance(det, str):
        g = _ALU_GRADE_RE.search(det)
        if g:
            det = _clean(re.sub(r"\b" + re.escape(g.group(1)) + r"\b", " ", det, flags=re.I))
            if det:
                result["details"] = det
            else:
                result.pop("details", None)
    if g:
        result["material"] = f"aluminum {g.group(1).upper()}"
    elif re.search(r"\balloy\b", (result["material"] + " " + (result.get("details") or "")).lower()):
        result["material"] = "aluminum alloy"   # keep "Aluminum Alloy" together, like a grade
    else:
        result["material"] = "aluminum"
    return result


def _finalize_motor(result, value):
    """Post-process a MOTOR component (after the live OR cached/LLM parse): fill the known
    Bosch line torque + 250W nominal, and capture the comm `protocol` (CAN bus / UART) when
    the system advertises it. Gated to motors so Bosch batteries/etc. are untouched; an
    explicit Nm/W in the text always wins."""
    if not (result and result.get("_kind") == "motor"):
        return result
    if result.get("manufacturer") == "Bosch":
        if result.get("torque_nm") is None:
            t = bosch_torque(value)
            if t is not None:
                result["torque_nm"] = t
        result.setdefault("power_w", 250)
    # "Ultro" is Aventon's mid-drive family (Ultro S / Ultro X); their trail rows
    # ("Aventon Ultro X") often omit "mid-drive" and parse/cache as hub. Force mid so
    # drive_type reads correctly and the eMTB structural gate qualifies (Current ADV/EXP).
    if result.get("placement") != "mid" and re.search(r"\bultro\b", value, re.I):
        result["placement"] = "mid"
    # communication protocol (only the real bus token — never the English word "can")
    if "protocol" not in result:
        mp = re.search(r"can[\s-]?bus|\buart\b", value, re.I)
        if mp:
            result["protocol"] = "UART" if mp.group(0).lower() == "uart" else "CAN bus"
            # drop the protocol token from model/details so it isn't echoed beside the field
            rx = re.compile(r"\bcan[\s-]?bus(?:\s+system)?\b|\buart\b", re.I)
            for fld in ("model", "details"):
                if result.get(fld):
                    cleaned = _clean(rx.sub("", result[fld]))
                    if cleaned:
                        result[fld] = cleaned
                    else:
                        result.pop(fld, None)
    return result


# Kinds whose rule parser now extracts more structured fields (and far shorter Details)
# than the cached LLM parse — prefer the rule parser for these (skip the LLM cache), so
# big run-on Details (wheel size / travel / chainline / thru-axle / headtube …) get split out.
_RULE_PREFERRED = {"frame", "fork", "shock"}


def parse_component(field: str, value, brand: str | None = None,
                    siblings: dict | None = None):
    """Structured dict for a known component field, else None. `siblings` lets the
    brake parser borrow a separate rotor field for diameter/thickness."""
    fn = _resolver(field)
    if fn is None or not isinstance(value, str) or not value.strip():
        return None
    kind = fn.__name__.lstrip("_")
    if _LLM_COMPONENTS and kind not in _RULE_PREFERRED:
        key = _hashlib.sha256(f"{kind}|{brand}|{value}".encode()).hexdigest()[:20]
        hit = _LLM_COMPONENTS.get(key)
        if hit:
            return _finalize_motor(_canon_material(_json.loads(_json.dumps(hit["parsed"]))), value)
    value = _dethousand(value)   # "1,200W" must parse as 1200, not 200
    sized = None if fn is _brake else _split_by_size(value)
    if fn is _brake:
        rotor = ""
        for k, sv in (siblings or {}).items():
            if "rotor" in k and isinstance(sv, str):
                rotor += " " + sv
        result = _brake(value, brand, rotor)
    elif sized:
        # attributes that vary by frame size (e.g. handlebar width/rise) are kept
        # under by_size; shared attributes stay at the top level.
        result = _parse_sized(fn, sized[0], sized[1], brand)
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
        _strip_parsed_from_details(result)
        _canon_material(result)
    return _finalize_motor(result, value)
