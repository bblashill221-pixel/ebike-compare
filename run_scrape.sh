#!/usr/bin/env bash
#
# Cron-friendly wrapper for the e-bike scrapers (Aventon + Lectric + Ride1Up +
# Specialized + Velotric + Heybike + Mokwheel + EVELO + Himiway + Euphree + Vvolt
# + Blix + Tern + Priority + Monarc + Velowave + Segway + Juiced + VIVI + CEMOTO).
# It archives the previous build to data/legacy/<date>/, then runs every scraper IN
# PARALLEL (up to SCRAPE_PARALLEL=6 at once) — each writes only its own
# data/current/<brand>_ebikes.json, so they can't collide. Once ALL scrapers finish, the
# sequential tail runs: enrich -> UPDATE COMPONENTS (price new/unresolved parts) ->
# CREATE ebike.json (normalize/analyze/build) -> publish to web/public/. Logs to
# logs/scrape.log. One scraper failing does not stop the others; the script exits non-zero
# if any scraper failed or the build didn't validate.
#
# Usage:  ./run_scrape.sh            (SCRAPE_PARALLEL=N to change concurrency)
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
    "scrape_cannondale.py|cannondale_ebikes|"
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
    "scrape_engwe.py|engwe_ebikes|"
    "scrape_wallke.py|wallke_ebikes|"
    "scrape_cyke.py|cyke_ebikes|"
    "scrape_leoguar.py|leoguar_ebikes|"
    "scrape_buzz.py|buzz_ebikes|"
    "scrape_magicycle.py|magicycle_ebikes|"
    "scrape_urtopia.py|urtopia_ebikes|"
    "scrape_trek.py|trek_ebikes|"
    "scrape_giant.py|giant_ebikes|"
    "scrape_vanpowers.py|vanpowers_ebikes|"
    "scrape_puckipuppy.py|puckipuppy_ebikes|"
    "scrape_bakcou.py|bakcou_ebikes|"
    "scrape_gotrax.py|gotrax_ebikes|"
    "scrape_retrospec.py|retrospec_ebikes|"
)

run_all() {
    local rc=0
    echo "===== $(date -Is) : starting scrape run ====="
    # Archive the previous build (scrape returns + its normalized) into
    # data/legacy/<date>/, dated by that build's generated_at (else today).
    if compgen -G "$CURRENT_DIR/*_ebikes.json" > /dev/null; then
        local oldstamp
        oldstamp=$("$PY" -c "import json,glob,sys;
f=glob.glob('$ACTIVE_DIR/ebike.json');
print((json.load(open(f[0])).get('generated_at','') or '')[:10]) if f else print('')" 2>/dev/null)
        [ -z "$oldstamp" ] && oldstamp="$(date +%F)"
        local dest="$LEGACY_DIR/$oldstamp"
        mkdir -p "$dest"
        mv -f "$CURRENT_DIR"/*_ebikes.json "$dest/" 2>/dev/null || true
        [ -f "$ACTIVE_DIR/ebike.json" ] && mv -f "$ACTIVE_DIR/ebike.json" "$dest/"
        echo "$(date -Is) : archived previous build -> $dest"
    fi
    # SCRAPE all brands in PARALLEL. Each scraper writes ONLY its own brand file and hits
    # its own vendor domain, so there is nothing to race on; we just bound how many run at
    # once (SCRAPE_PARALLEL, default 6) since the Playwright/Chromium scrapers are RAM-heavy.
    # Each job logs to its own file; the logs are stitched in declared order afterward so
    # parallel output doesn't interleave, and a per-job failure marker sets rc=1.
    local MAX_PAR="${SCRAPE_PARALLEL:-6}"
    local jobdir; jobdir="$(mktemp -d)"
    echo "--- $(date -Is) : scraping ${#SCRAPERS[@]} brands, up to $MAX_PAR in parallel ---"
    for entry in "${SCRAPERS[@]}"; do
        while [ "$(jobs -rp | wc -l)" -ge "$MAX_PAR" ]; do wait -n; done
        IFS='|' read -r script base args <<< "$entry"
        (
            latest="$CURRENT_DIR/${base}.json"
            blog="$jobdir/${base}.log"
            echo "--- $(date -Is) : $script ---" > "$blog"
            if "$PY" "$PROJECT_DIR/$script" -o "$latest" $args >> "$blog" 2>&1; then
                echo "$(date -Is) : OK -> $latest" >> "$blog"
            else
                echo "$(date -Is) : FAILED -> $script" >> "$blog"
                touch "$jobdir/${base}.failed"
            fi
        ) &
    done
    wait   # barrier: every scraper has finished before enrichment/build begins
    for entry in "${SCRAPERS[@]}"; do
        IFS='|' read -r script base _ <<< "$entry"
        [ -f "$jobdir/${base}.log" ] && cat "$jobdir/${base}.log"
        [ -f "$jobdir/${base}.failed" ] && rc=1
    done
    rm -rf "$jobdir"
    # Fill any missing per-model warranty (brand-level policy) and refresh the
    # component cost estimates from the final data.
    echo "--- $(date -Is) : fill_warranty + shipping/accessories + component costs ---"
    "$PY" "$PROJECT_DIR/fill_warranty.py" || true
    # Flag new arrivals from each brand's own product tags (drives the "New"
    # badge + filter); brands that don't tag new arrivals are left as not-new.
    "$PY" "$PROJECT_DIR/enrich_new_flag.py" || true
    "$PY" "$PROJECT_DIR/enrich_shipping_accessories.py" || true
    # Specialized & Ride1Up are not Shopify, so their accessory catalogs are scraped
    # separately (enrich_shipping_accessories leaves non-Shopify catalogs untouched).
    "$PY" "$PROJECT_DIR/scrape_specialized_accessories.py" || true
    "$PY" "$PROJECT_DIR/scrape_ride1up_accessories.py" || true
    # Fill each bike's rear-rack max load from the brand's rack accessory pages
    # (the bike's own sheet often omits it). Needs available_accessories above.
    "$PY" "$PROJECT_DIR/enrich_rack_load.py" || true
    # Per-frame-size rider-height charts (multi-size brands) -> model.frame_sizes
    # + the full rider-height envelope. Single-size brands are unaffected.
    "$PY" "$PROJECT_DIR/enrich_frame_sizes.py" || true
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
    # Order of operations: scrape all (above) -> UPDATE COMPONENTS -> CREATE ebike.json.
    # Delegated to the shared offline pipeline with --refresh-prices, which runs:
    # normalize -> component_catalog -> resolve_component_prices scrape (price new/unresolved
    # parts off the freshly built catalog) -> write-catalog -> analyze -> audits -> validate
    # -> diff_changes -> intern_components -> slim_web_build -> promote to web/public/.
    # (For a price-only refresh without re-scraping brands, use update_prices.sh.)
    if ! "$PROJECT_DIR/rebuild_offline.sh" --refresh-prices; then
        echo "$(date -Is) : rebuild_offline (components+build+publish) FAILED — web/public/ left untouched"
        rc=1
    fi
    echo "===== $(date -Is) : run complete (rc=$rc) ====="
    echo
    return $rc
}

run_all >> "$LOG" 2>&1
exit $?
