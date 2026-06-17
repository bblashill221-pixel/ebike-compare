#!/usr/bin/env bash
#
# Offline rebuild of data/current/active/ebikes_normalized.json from the existing
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
# Offline: fold the cached component prices (retail + wholesale) into the freshly
# rebuilt catalog so analyze.py's value roll-ups pick them up. No network — the
# actual price refresh (resolve_component_prices.py run) only happens in run_scrape.sh.
run resolve_component_prices.py write-catalog
run estimate_component_costs.py -o "$PROJECT_DIR/data/current/component_cost_estimates.json"
run analyze.py
run audit.py
# Correctness triage (advisory): flag likely-misclassified / misparsed bikes.
run audit_anomalies.py

if "$PY" "$PROJECT_DIR/validate_build.py"; then
    run diff_changes.py
    cp "$PROJECT_DIR/data/current/active/ebikes_normalized.json" \
       "$PROJECT_DIR/web/public/ebikes_normalized.json"
    echo "$(date -Is) : validated + promoted to web/public/"
else
    echo "$(date -Is) : validation FAILED — web/public/ left untouched (last-good kept)" >&2
    exit 1
fi
