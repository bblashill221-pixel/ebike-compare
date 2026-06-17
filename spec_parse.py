#!/usr/bin/env python3
"""
Shared spec-parsing helpers for the analysis utilities.

The scraped specs are free-text (`label -> value` strings) that differ across
brands, so every derived number has to be pulled out with tolerant regexes.
These helpers are the small, generic primitives reused by `analyze.py` (and
mirror the style already used in `estimate_component_costs.py`).
"""
from __future__ import annotations

import re


def num(pattern: str, text: str) -> float | None:
    """First capture group of `pattern` in `text`, as a float (or None)."""
    m = re.search(pattern, text, re.I)
    return float(m.group(1)) if m else None


# Mid-drive vs hub: most premium mid-drives never say "mid-drive" in the spec —
# they're identified by the motor brand/model. Recognize the known mid-drive
# systems (Bosch — all e-bike drive units, Brose, Shimano STEPS/EP, Yamaha PW, TQ
# HPR, DJI Avinox, Bafang M-series/Ultra, Specialized full-power 2.x/3.x) plus the
# literal wording. Carve-outs for look-alike HUBs: Mahle (Specialized SL / Creo SL
# rear hub) and Bafang G0xx geared hubs are NOT mid-drive.
_MID_DRIVE_RE = re.compile(
    r"mid[\s-]?drive|mid[\s-]?motor|bottom bracket"
    r"|bosch|brose|yamaha|shimano\s*(?:ep|steps|e\d{4})|\bsteps\b"
    r"|\btq\b|\bhpr\b|avinox"
    r"|bafang\s*(?:m\d|ultra|max)|\bm[456]\d{2}\b"
    r"|specialized\s*[23]\.\d", re.I)
_HUB_OVERRIDE_RE = re.compile(r"mahle|bafang\s*g0|\bg0\d\d\b", re.I)


def is_mid_drive(text) -> bool:
    """True when the motor text names a mid-drive system (by wording or brand/model);
    the hub-override patterns (Mahle, Bafang G0xx) win so SL/geared-hub motors stay hub."""
    t = str(text or "")
    return bool(_MID_DRIVE_RE.search(t)) and not _HUB_OVERRIDE_RE.search(t)


def all_nums(pattern: str, text: str) -> list[float]:
    """Every first-group match of `pattern` in `text`, as floats."""
    return [float(g) for g in re.findall(pattern, text, re.I)]


def find_spec(specs: dict, *keywords: str) -> str:
    """Concatenate the values of every spec row whose label matches a keyword."""
    hits = []
    for label, value in specs.items():
        low = label.lower()
        if any(k in low for k in keywords):
            hits.append(str(value))
    return " | ".join(hits)


def blob(specs: dict) -> str:
    """The whole spec table (labels + values) as one lowercased string."""
    parts = []
    for label, value in specs.items():
        parts.append(str(label))
        parts.append(str(value))
    return " | ".join(parts).lower()


def kg_to_lb(kg: float) -> float:
    return round(kg * 2.2046226, 1)


# Rider-height ranges are free text ("4'11\" - 6'3\"", curly quotes, cm, or a
# per-size dict {"R": "...", "L": "..."}). For the "does any frame size fit me?"
# filter we only need the overall min/max, so we collect EVERY height token in the
# value and take the envelope -- no need to model individual sizes.
_FEET_INCH = re.compile(r"(\d)\s*['′]\s*(\d{1,2})?")   # 5'10", 5'10, 5' (straight/curly ')
_CM = re.compile(r"(\d{2,3})\s*(?:[-–~]\s*(\d{2,3}))?\s*cm")   # "200cm" or "150 - 200 cm"
_DEC_FT = re.compile(r"(\d(?:\.\d)?)\s*(?:ft\b|feet\b)")


def height_tokens_in(text: str) -> list[float]:
    """Every height mentioned in `text`, in inches. Prefers feet-inch notation;
    falls back to centimetres, then decimal feet. Returns [] when none parse."""
    # normalise prime + curly-quote + en/em-dash variants to ASCII ' " -
    t = (str(text).replace("″", '"').replace("′", "'")
         .replace("’", "'").replace("‘", "'").replace("”", '"').replace("“", '"')
         .replace("–", "-").replace("—", "-"))
    feet_inch = [int(f) * 12 + (int(i) if i else 0) for f, i in _FEET_INCH.findall(t)]
    if feet_inch:
        return [float(v) for v in feet_inch]
    if "cm" in t.lower():
        return [round(float(c) / 2.54, 1)
                for lo, hi in _CM.findall(t) for c in (lo, hi) if c]
    return [round(float(f) * 12, 1) for f in _DEC_FT.findall(t)]


def height_range_in(value) -> tuple[float, float] | None:
    """(min_in, max_in) across a rider-height value -- a range string or a
    per-frame-size dict of range strings -- or None when no height parses."""
    parts = value.values() if isinstance(value, dict) else [value]
    toks = [tk for p in parts for tk in height_tokens_in(p)]
    return (min(toks), max(toks)) if toks else None


def percentile_rank(value: float, sorted_values: list[float]) -> float:
    """
    Fraction of the field this value is >= (0..1), via the midpoint method so
    ties land sensibly. `sorted_values` must be ascending and non-empty.
    """
    n = len(sorted_values)
    below = sum(1 for v in sorted_values if v < value)
    equal = sum(1 for v in sorted_values if v == value)
    return round((below + equal / 2) / n, 3)
