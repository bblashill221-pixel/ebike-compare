#!/usr/bin/env bash
#
# Offline rebuild of data/current/active/ebike.json from the existing
# per-brand scrape returns (data/current/*_ebikes.json) + curated artifacts
# (data/curated/*) — the compute tail only, NO scraping and NO network
# enrichment. This is the "safe regen" subset: deterministic and reproducible,
# useful for iterating on normalize/analyze or rebuilding after editing a curated
# override without re-hitting every brand site.
#
# Promotes the result to web/public/ only if validate_build.py passes, so a known
# good build isn't replaced by a broken one.
#
# Usage:  ./rebuild_offline.sh
set -uo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"
PY="$PROJECT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY=python3

run() { echo "--- $(date -Is) : $1"; "$PY" "$PROJECT_DIR/$1" "${@:2}"; }

run normalize.py
run component_catalog.py
# Offline: fold the catalog's component retail prices (researched or brand/spec
# estimate) into the freshly rebuilt catalog so analyze.py's value roll-up picks them
# up. No network — the price refresh (resolve_component_prices.py run) is run_scrape.sh.
run resolve_component_prices.py write-catalog
run analyze.py
run audit.py
# Correctness triage (advisory): flag likely-misclassified / misparsed bikes.
run audit_anomalies.py
# Per-scraper key/icon-field audit -> data/audits/<brand>.json (offline: refresh the
# resolution logs from this build; the resolver's network passes are opt-in via
# `audit_scrapers.py --resolve`).
run audit_scrapers.py

if "$PY" "$PROJECT_DIR/validate_build.py"; then
    run diff_changes.py
    # Rewrite the active build with the content-addressed `components` table + refs
    # (every component once, priced, linked to the catalog). Runs AFTER the readers
    # above (which use inline specs) and before the web payload.
    run intern_components.py
    # Emit the SLIM web payload (drops dead fields + minifies; the components table +
    # refs pass through) rather than copying the full record verbatim.
    run slim_web_build.py
    # the QA page (/qa) fetches anomalies.json from web/public — promote it too so
    # the triage list stays in sync with the data, not stale from a prior build
    cp "$PROJECT_DIR/data/current/anomalies.json" \
       "$PROJECT_DIR/web/public/anomalies.json"
    echo "$(date -Is) : validated + promoted to web/public/"
else
    echo "$(date -Is) : validation FAILED — web/public/ left untouched (last-good kept)" >&2
    exit 1
fi
