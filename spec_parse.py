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


def percentile_rank(value: float, sorted_values: list[float]) -> float:
    """
    Fraction of the field this value is >= (0..1), via the midpoint method so
    ties land sensibly. `sorted_values` must be ascending and non-empty.
    """
    n = len(sorted_values)
    below = sum(1 for v in sorted_values if v < value)
    equal = sum(1 for v in sorted_values if v == value)
    return round((below + equal / 2) / n, 3)
