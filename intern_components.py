#!/usr/bin/env python3
"""
Pipeline step: rewrite the normalized build IN PLACE with a content-addressed
`components` table + references (see component_refs.py).

Runs near the END of the pipeline — after analyze/audit/validate/diff, which read
inline specs — and before slim_web_build.py. The result is the source of truth the app
fetches: every component lives once in `doc.components` (keyed, priced, linked to
component_catalog.json) and each `model.specs[group][field]` is the string key of its
entry. Idempotent: re-running rehydrates first, then re-interns from the current catalog.

Usage: python intern_components.py [-i ebike.json] [-o out.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import component_refs as CR

HERE = Path(__file__).parent
SRC = HERE / "data" / "current" / "active" / "ebike.json"
CATALOG = HERE / "data" / "component_catalog.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", default=str(SRC))
    ap.add_argument("-o", "--output", default=None, help="defaults to --input (in place)")
    args = ap.parse_args()
    out = args.output or args.input

    doc = json.loads(Path(args.input).read_text())
    catalog = json.loads(Path(CATALOG).read_text()).get("components") or {}
    CR.rehydrate(doc)             # idempotent: normalize a previously-interned file first
    CR.intern(doc, catalog)
    Path(out).write_text(json.dumps(doc, indent=2, ensure_ascii=False))
    print(f"[intern] {out}: {len(doc.get('components') or {})} components, refs wired")


if __name__ == "__main__":
    main()
