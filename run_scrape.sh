#!/usr/bin/env bash
#
# Cron-friendly wrapper for the e-bike scrapers (Aventon + Lectric + Ride1Up +
# Specialized + Velotric + Heybike + Mokwheel + EVELO + Himiway + Euphree + Vvolt
# + Blix + Tern + Priority + Monarc + Velowave + Segway + Juiced + VIVI + CEMOTO).
# It archives the previous build (scrape returns + normalized) to
# data/legacy/<date>/, then runs each scraper with the project's venv writing to
# data/current/<brand>_ebikes.json, then enrich -> normalize
# (data/current/active/ebikes_normalized.json) -> metrics. Logs to logs/scrape.log.
# One scraper failing does not stop the other; the script exits non-zero if any
# scraper failed.
#
# Usage:  ./run_scrape.sh
# Cron:   0 6 * * 1  /home/bblashill/ebike-compare/run_scrape.sh
#
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

PY="$PROJECT_DIR/.venv/bin/python"
LOG="$PROJECT_DIR/logs/scrape.log"
# Layout: the live build is data/current/ (scrape returns + schema + cost estimates)
# with the normalized output in data/current/active/. Each superseded build is
# archived to data/legacy/<date>/ (its scrape returns + that build's normalized).
CURRENT_DIR="$PROJECT_DIR/data/current"
ACTIVE_DIR="$CURRENT_DIR/active"
LEGACY_DIR="$PROJECT_DIR/data/legacy"
mkdir -p "$ACTIVE_DIR" "$LEGACY_DIR" "$PROJECT_DIR/logs"

# scraper script | output basename | extra args
SCRAPERS=(
    "scrape_aventon.py|aventon_ebikes|--concurrency 4"
    "scrape_lectric.py|lectric_ebikes|"
    "scrape_ride1up.py|ride1up_ebikes|"
    "scrape_specialized.py|specialized_ebikes|--concurrency 3"
    "scrape_velotric.py|velotric_ebikes|"
    "scrape_heybike.py|heybike_ebikes|"
    "scrape_mokwheel.py|mokwheel_ebikes|"
    "scrape_evelo.py|evelo_ebikes|"
    "scrape_himiway.py|himiway_ebikes|"
    "scrape_euphree.py|euphree_ebikes|"
    "scrape_vvolt.py|vvolt_ebikes|"
    "scrape_blix.py|blix_ebikes|"
    "scrape_tern.py|tern_ebikes|"
    "scrape_priority.py|priority_ebikes|"
    "scrape_monarc.py|monarc_ebikes|"
    "scrape_velowave.py|velowave_ebikes|"
    "scrape_segway.py|segway_ebikes|"
    "scrape_juiced.py|juiced_ebikes|"
    "scrape_vivi.py|vivi_ebikes|"
    "scrape_cemoto.py|cemoto_ebikes|"
    "scrape_wired.py|wired_ebikes|"
    "scrape_magician.py|magician_ebikes|"
)

run_all() {
    local rc=0
    echo "===== $(date -Is) : starting scrape run ====="
    # Archive the previous build (scrape returns + its normalized) into
    # data/legacy/<date>/, dated by that build's generated_at (else today).
    if compgen -G "$CURRENT_DIR/*_ebikes.json" > /dev/null; then
        local oldstamp
        oldstamp=$("$PY" -c "import json,glob,sys;
f=glob.glob('$ACTIVE_DIR/ebikes_normalized.json');
print((json.load(open(f[0])).get('generated_at','') or '')[:10]) if f else print('')" 2>/dev/null)
        [ -z "$oldstamp" ] && oldstamp="$(date +%F)"
        local dest="$LEGACY_DIR/$oldstamp"
        mkdir -p "$dest"
        mv -f "$CURRENT_DIR"/*_ebikes.json "$dest/" 2>/dev/null || true
        [ -f "$ACTIVE_DIR/ebikes_normalized.json" ] && mv -f "$ACTIVE_DIR/ebikes_normalized.json" "$dest/"
        echo "$(date -Is) : archived previous build -> $dest"
    fi
    for entry in "${SCRAPERS[@]}"; do
        IFS='|' read -r script base args <<< "$entry"
        local latest="$CURRENT_DIR/${base}.json"
        echo "--- $(date -Is) : $script ---"
        if "$PY" "$PROJECT_DIR/$script" -o "$latest" $args; then
            echo "$(date -Is) : OK -> $latest"
        else
            echo "$(date -Is) : FAILED -> $script"
            rc=1
        fi
    done
    # Fill any missing per-model warranty (brand-level policy) and refresh the
    # component cost estimates from the final data.
    echo "--- $(date -Is) : fill_warranty + shipping/accessories + component costs ---"
    "$PY" "$PROJECT_DIR/fill_warranty.py" || true
    "$PY" "$PROJECT_DIR/enrich_shipping_accessories.py" || true
    # Fill each bike's rear-rack max load from the brand's rack accessory pages
    # (the bike's own sheet often omits it). Needs available_accessories above.
    "$PY" "$PROJECT_DIR/enrich_rack_load.py" || true
    "$PY" "$PROJECT_DIR/add_geometry.py" || true
    "$PY" "$PROJECT_DIR/add_configurations.py" || true
    "$PY" "$PROJECT_DIR/add_config_colors.py" || true
    "$PY" "$PROJECT_DIR/add_available_options.py" || true
    "$PY" "$PROJECT_DIR/add_pricing.py" || true
    # Merge per-color duplicate products (Monarc) and family-link frame-style
    # variants, then split spec-bearing tiers (battery size / version / frame
    # style / Lectric configs) into sibling model entries so downstream metrics
    # are per-configuration accurate.
    "$PY" "$PROJECT_DIR/merge_color_siblings.py" || true
    "$PY" "$PROJECT_DIR/expand_tiers.py" || true
    # Each tiered sibling gets a URL that preselects its configuration on the
    # brand site, where the platform supports it (best effort).
    "$PY" "$PROJECT_DIR/add_deep_links.py" || true
    # Normalize unifies all brands AND does the detailed spec grouping + component
    # parsing into ebikes_normalized.json (the single transform step).
    "$PY" "$PROJECT_DIR/normalize.py" || true
    # Aggregate the fleet-wide part catalog (manufacturer + model number per
    # component) used for aftermarket price lookups; prior lookups are preserved.
    "$PY" "$PROJECT_DIR/component_catalog.py" || true
    # Metrics last: BOM cost estimates, then the typed-fact + scoring analysis layer.
    "$PY" "$PROJECT_DIR/estimate_component_costs.py" \
        -o "$CURRENT_DIR/component_cost_estimates.json" || true
    "$PY" "$PROJECT_DIR/analyze.py" || true
    # Data audit last: flag models missing expected spec values (report + CSV +
    # per-model annotation). Reads typed specs only; safe to re-run.
    "$PY" "$PROJECT_DIR/audit.py" || true
    echo "===== $(date -Is) : run complete (rc=$rc) ====="
    echo
    return $rc
}

run_all >> "$LOG" 2>&1
exit $?
