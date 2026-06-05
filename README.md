# E-Bike Spec Scrapers

Playwright screen scrapers that extract full physical + technical specifications
for every model from 13 e-bike brands, writing structured JSON:

| Brand | Scraper | Output | Platform |
|-------|---------|--------|----------|
| [Aventon](https://www.aventon.com) | `scrape_aventon.py` | `aventon_ebikes.json` | Shopify |
| [Lectric](https://lectricebikes.com) | `scrape_lectric.py` | `lectric_ebikes.json` | Shopify |
| [Ride1Up](https://ride1up.com) | `scrape_ride1up.py` | `ride1up_ebikes.json` | WooCommerce |
| [Specialized](https://www.specialized.com) | `scrape_specialized.py` | `specialized_ebikes.json` | Next.js / SFCC |
| [Velotric](https://www.velotricbike.com) | `scrape_velotric.py` | `velotric_ebikes.json` | Shopify |
| [Heybike](https://www.heybike.com) | `scrape_heybike.py` | `heybike_ebikes.json` | Shopify |
| [Mokwheel](https://www.mokwheel.com) | `scrape_mokwheel.py` | `mokwheel_ebikes.json` | Shopify |
| [EVELO](https://www.evelo.com) | `scrape_evelo.py` | `evelo_ebikes.json` | Shopify |
| [Himiway](https://himiwaybike.com) | `scrape_himiway.py` | `himiway_ebikes.json` | Shopify |
| [Euphree](https://euphree.com) | `scrape_euphree.py` | `euphree_ebikes.json` | Shopify |
| [Vvolt](https://vvolt.com) | `scrape_vvolt.py` | `vvolt_ebikes.json` | Shopify |
| [Blix](https://blixbike.com) | `scrape_blix.py` | `blix_ebikes.json` | Shopify |
| [Tern](https://www.ternbicycles.com) | `scrape_tern.py` | `tern_ebikes.json` | Drupal |

Their product structures differ enough to need separate scrapers (see each
section below). All emit the same JSON shape: `{source, scraped_at, model_count,
models:[…]}`, where each model has a `warranty` string, `shipping` ({cost, free}), `free_accessories` (the $0 items bundled with the bike), `geometry` (standover, reach, stack, wheelbase, rider-height range, …), `specs.{physical,technical,all}`, and
`options.colors` = `[{name, hex, swatch_image, image}]`.

> **Output layout:** all generated JSON lives under `data/` (not next to the
> scrapers): `data/<brand>_ebikes.json` (live per-brand), `data/ebikes_normalized.json`,
> `data/component_cost_estimates.json`, `data/ebikes.schema.json`; dated snapshots
> in `data/current/` (newest per brand) and `data/legacy/` (history).
 Models with variants also carry a `configurations` list — each entry is one variant with its `options`, `price`, and full `color` scheme (colour availability is per-configuration, e.g. Ride1Up Vorsa).

Each color carries its swatch as a **hex code or an image link** (hex preferred):
`hex` is the solid swatch colour (when the site exposes one, else sampled/curated
best-effort); `swatch_image` is the swatch's background-image URL and is only set
as a **fallback when no `hex` was found** (so a color has one or the other, never
both); `image` is the bike's full product photo in that colour.

Each file also carries a brand-level `available_accessories` catalog (`[{name, price, free}]`, `free` = $0); `free_accessories` per model lists the bundled $0 items.

Each scraper also emits a top-level `logo` field — the brand's company logo (a
`LOGO` constant in each `scrape_*.py`), surfaced into the normalized dataset's
`brands[]` (`{brand, source, logo, model_count, available_accessories}`) for display
on the site. A `logo` is either a **remote URL** (the brand's own CDN) or a
**repo-relative self-hosted asset** under `assets/logos/` — the site should treat any
value not starting with `http` as a local static asset. EVELO and Specialized render
their logos as inline SVG with no standalone CDN asset, so their true wordmarks are
extracted and self-hosted at `assets/logos/{evelo,specialized}.svg`.

> Aventon and Velotric expose only a brand **icon** (favicon), not a wordmark, and
> render their header logo client-side, so there's no scrapeable wordmark. To
> self-host a real wordmark for either, drop `assets/logos/<brand>.svg` (or `.png`)
> in and set that scraper's `LOGO` to `assets/logos/<brand>.<ext>`.

---

# Aventon

Discovers every e-bike model and extracts the **full specification table** for
each one — split into **physical** and **technical** groups, plus a flat `all`
map.

> Note: the brand is **Aventon** (commonly mistyped "Avention").

## How it works

1. **Model discovery** — reads Aventon's Shopify catalog feed
   (`/collections/ebikes/products.json`) to get every model, its URL, price, and
   color/size options. No browser needed for this step.
2. **Spec extraction** — for each product page, Playwright (headless Chromium)
   opens the "Technical Specifications" drawer and reads every
   `.property-line` row as a `label → value` pair.
3. **Classification** — each spec is bucketed into `physical` (frame, fork,
   wheels, tires, brakes, drivetrain, weight, dimensions, …) or `technical`
   (motor, battery, range, charger, controller, display, class, …).
4. **Colors** — `options.colors` is a list of `{name, hex, image}`. `hex` is read
   from each on-page color swatch's background-color (the swatch button's
   `data-sl` gives the name); `image` is the color-correct variant photo. A small
   curated map is kept only as a fallback when a swatch isn't found.

## Output (`aventon_ebikes.json`)

```jsonc
{
  "source": "https://www.aventon.com",
  "scraped_at": "2026-06-03T...Z",
  "model_count": 18,
  "models": [
    {
      "title": "Aventure 3 Ebike",
      "url": "https://www.aventon.com/products/aventure-3-ebike",
      "price_from": 1999.0,
      "options": {
        "Size": ["Regular", "Large"],
        "colors": [{ "name": "Matcha", "hex": "#8a9a5b", "image": "https://cdn.shopify.com/...png" }]
      },
      "spec_count": 54,
      "specs": {
        "physical":  { "WEIGHT": "76 lbs", "FRAME": "6061 Aluminum...", ... },
        "technical": { "MOTOR": "36V, 750W Hub Drive", "BATTERY": "...733Wh...", ... },
        "all":       { ...every spec, in page order... }
      }
    }
  ]
}
```

---

# Lectric

Lectric's catalog lists **each color/config as a separate Shopify product**
(~39 SKUs). The scraper groups them into **8 model families** (by `product_type`)
and, per family, captures:

- **Specs** — headline tiles (`#productFeaturesDesktop .feature-item`) plus the
  feature cards (`#specifications .specifications-list li`), split into
  `physical` / `technical` / `all`. Per-config specs are preserved under
  `configs`; the model-level `specs` merges them, keeping the most specific value
  on collisions.
- **Feature options** — `colors` (name, `hex`, color-correct `image`),
  `frame_styles`, `battery` configs, and `performance` options.
- **Accessories** — `included` (the free-with-purchase bundle) vs `add_ons`
  (paid upgrades), each with a price.
- eTrikes (XP Trike2) are included and tagged `"vehicle_type": "trike"`.

> Each color button on the PDP is an SVG bike silhouette whose `<path>` fill is
> the actual swatch color, so `hex` is read straight from that fill. (A small
> curated map is kept only as a fallback for the rare color with no button.) The
> button links to that color's product page, so `image` is the color's own photo.

## Output (`lectric_ebikes.json`)

```jsonc
{
  "source": "https://lectricebikes.com",
  "model_count": 8,
  "models": [
    {
      "model": "Lectric XP4",
      "family_code": "Bike-4",
      "vehicle_type": "bike",
      "price_range": { "min": 999, "max": 1299, "currency": "USD" },
      "options": {
        "colors": [{ "name": "Pine Green", "hex": "#2f4a3a", "image": "https://cdn.shopify.com/...png" }],
        "frame_styles": ["High-Step", "Step-Thru"],
        "battery": ["Long-Range", "Standard"],
        "performance": ["Standard Motor & Battery -$300", "Upgraded Motor & Battery +$0 ..."]
      },
      "configs": [ { "label": "...", "url": "...", "specs": { ... } } ],
      "specs": { "physical": { ... }, "technical": { ... }, "all": { ... } },
      "accessories": {
        "included": [{ "name": "LevelUp Rack", "price": 79 }],
        "add_ons":  [{ "name": "Fast Charger", "price": 149 }]
      }
    }
  ]
}
```

> Note: heavy PDPs (long-range / dual-battery configs) hydrate unreliably above
> 2 concurrent pages, so the Lectric default `--concurrency` is **2**.

---

# Ride1Up

Ride1Up runs on **WooCommerce** (not Shopify). Models are discovered from the
"bikes" category grid (`/product-category/bikes/`), then each product page yields:

- **Specs** — the "Components & Tech Specs" list (`.component-text` →
  `.component-title` / `.component-subtitle`), split into `physical` /
  `technical` / `all`, plus the headline highlight grid.
- **Options** — the WooCommerce variation attributes (frame type, drivetrain,
  battery size, …) with their display names, read from the
  `data-product_variations` JSON on the variations form.
- **Colors** — `{name, hex, image}`: names from the `pa_color` `<select>`,
  per-color photo from each color's variation image. Ride1Up uses **image**
  swatches (not solid-color chips), so `hex` is sampled from the swatch image's
  centre pixel via a same-origin canvas.

## Output (`ride1up_ebikes.json`)

```jsonc
{
  "source": "https://ride1up.com",
  "category": "bikes",
  "model_count": 11,
  "models": [
    {
      "model": "PRODIGY V2",
      "url": "https://ride1up.com/product/prodigy-v2/",
      "price_range": { "min": 2295, "max": 2495, "currency": "USD" },
      "options": {
        "frame-type": ["ST", "XR"],
        "drive-train": ["Belt/CVT", "Chain"],
        "colors": [{ "name": "Onyx Black", "hex": "#232323", "image": "https://ride1up.com/...jpg" }]
      },
      "specs": {
        "physical":  { "Brakes": "Tektro HD-M745 180mm Hydraulic", ... },
        "technical": { "Motor": "Brose TF Sprinter ... 90nm torque", "Battery": "36V 14ah ...", ... },
        "all":       { ... }
      }
    }
  ]
}
```

---

# Specialized

Specialized runs a **Next.js / Salesforce Commerce Cloud** site. The current
e-bike lineup is discovered from the e-bikes category page (`/shop/ebikes`,
rendered + scrolled to load all cards), then each product page yields:

- **Specs** — the `SpecContainer` sections (E-Bike, Frameset, Suspension, Brakes,
  Drivetrain, Wheels & Tires, Cockpit, Accessories, Weight, …), each a
  category → name → value. Specs are classified `technical` when their category
  is electronic (E-Bike: motor, battery, charger, UI/remote), else `physical`.
- **Options** — frame `sizes` (from the geometry table) and `colors`.
- **Colors** — `{name, hex, image}`: name from the swatch `aria-label`, **hex**
  from the swatch's inline `background-color`, and `image` is that color's hero
  photo (captured by clicking each swatch).
- **Price** — `price_range` from the page's JSON-LD `Product` offers.

```jsonc
{
  "source": "https://www.specialized.com",
  "category": "ebikes",
  "models": [
    {
      "model": "Turbo Vado 3 X 4.0",
      "url": "https://www.specialized.com/us/en/turbo-vado-3-x-40/p/...",
      "price_range": { "min": 5499.99, "max": 5499.99, "currency": "USD" },
      "options": {
        "sizes": ["S", "M", "L", "XL"],
        "colors": [{ "name": "Gloss Obsidian / Satin Silver Dust Frost", "hex": "#252127", "image": "https://assets.specialized.com/...HERO-PDP" }]
      },
      "specs": { "physical": { ... }, "technical": { "Motor": "...", "Battery": "...", ... }, "all": { ... } }
    }
  ]
}
```

> Specialized's sitemap contains thousands of discontinued products, so discovery
> uses the live `/shop/ebikes` category page instead — that's the current lineup.

---

# Velotric

Velotric is a Shopify store. Models come from the `electric-bikes` collection
feed; each product page is rendered with Playwright for its spec grid.

- **Specs** — the spec grid (`.specs-components-grid-item-title` →
  `.specs-variant` value): Motor, Battery, Cell, Charger, Sensor, Display, Frame,
  Fork, Brake, drivetrain, … split into `physical` / `technical`.
- **Options** — Shopify variant options (Size, Style, Package) + `colors`.
- **Colors** — `{name, hex, image}`: name from the `Color` option, color-correct
  `image` from the variant photo, and `hex` read from the page's
  `data-colors-patterns` map (Velotric's `ColorName::#hex` swatch lookup; the
  first hex of each gradient swatch is used as the base color).

```jsonc
{
  "source": "https://www.velotricbike.com",
  "collection": "electric-bikes",
  "models": [
    {
      "model": "Velotric Discover 3 Ebike",
      "price_from": 1499.0,
      "options": {
        "Size": ["Large", "Regular"],
        "colors": [{ "name": "Emerald Green", "hex": "#133834", "image": "https://cdn.shopify.com/...png" }]
      },
      "specs": { "physical": { ... }, "technical": { "Motor": "48V, 750W ...", ... }, "all": { ... } }
    }
  ]
}
```

---

# Heybike

Heybike is a Shopify store. Models come from the `electric-bike` collection
feed; each product page is rendered with Playwright for its spec accordions.

- **Specs** — the spec accordion sections, expanded and read as label → value.
  Heybike uses two templates (`<h6>`+`<p>`, and `<p><strong>Label:</strong>…`),
  so both are handled. Split into `physical` / `technical`.
- **Options** — Shopify variant options (Version) + `colors`.
- **Colors** — `{name, hex, image}`: name from the `Color` option, color-correct
  `image` from the variant photo. Heybike uses **image swatches** and only
  exposes a `--swatch-background` colour keyword, so `hex` is best-effort: solid
  CSS colours resolve (e.g. Ruby Red → `#ff0000`); fancy names (pearl, sunset)
  stay `null`. The per-color `image` is the reliable visual.

---

# Mokwheel

Mokwheel is a Shopify store. Models come from the `electric-bikes` collection
feed; each product page is rendered with Playwright for its keynote spec section.

- **Specs** — the `.alp-keynote-specification` section, whose tabs mix two row
  markups (`<span>name</span><span>value</span>` for Geometry, `<b>name</b>
  <span>value</span>` for Technical/Performance); a generic scan handles both.
  Split into `physical` / `technical`.
- **Options** — Shopify variant options (Size) + `colors`.
- **Colors** — `{name, hex, image}`: name from the `Color` option, color-correct
  `image` from the variant photo. Mokwheel uses image swatches, so `hex` is
  **sampled from the swatch chip image's centre pixel** (same-origin canvas) —
  best-effort representative colour; the `image` is the reliable visual.

---

# EVELO

EVELO is a Shopify store. Models come from the `evelo-bikes` collection feed;
each product page is rendered with Playwright for its spec list.

- **Specs** — the `.spec-item` blocks (an `<h4>` label + a `.copy` value):
  Motor, Battery, Charger, Transmission, Frame, Fork, Wheels, Brakes,
  Drivetrain, Display, … split into `physical` / `technical`.
- **Price** — from the page's JSON-LD `Product` offer.
- **Colors** — EVELO sells a **single configuration** per model (no colour
  variants), so `options.colors` holds one `"Standard"` entry carrying the
  bike's product `image`; `hex` and `swatch_image` are null.

---

# Tern

Tern runs a **Drupal** site (no Shopify `products.json`) and sells both electric
and non-electric folding bikes, so this scraper works differently:

1. **Discovery** — reads the `/us/bikes/all` listing and collects every
   `/us/bikes/<id>/<slug>` link. Family **landing** pages (e.g. `/gsd`) carry no
   spec grid and are dropped automatically.
2. **Spec extraction** — each product page is server-rendered; Playwright reads
   the `#tech_specs` grid, where every row is a label (`.text-header`) followed by
   its value cell (`.text-gray-700 … col-span-2`). Split into `physical` /
   `technical` / `all`.
3. **Electric filter** — only models with a **Motor/Battery** spec are kept, so
   acoustic folders (Verge, Node, Link, BYB, Eclipse, Short Haul) are excluded;
   the GSD, HSD, Quick Haul, NBD, Vektron and Orox e-bikes remain.
4. **Colors** — `{name, hex, swatch_image, image}`: name from each swatch's
   `title`, **hex** read straight from the swatch's inline `background-color`
   (so hex coverage is complete); `image` is the model's hero photo.
5. **Price** — parsed from the page's `.field-pricing` ($ amount).

> Tern's product pages don't surface a warranty statement in a scannable form, so
> `warranty` is left `null` (rather than guessing a period).

---

# Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
```

Chromium also needs some system libraries. On a machine with root:

```bash
sudo .venv/bin/python -m playwright install-deps chromium
```

(This repo already contains a no-root local copy of those libraries under
`.chromium-deps/`; the scraper auto-detects it and sets `LD_LIBRARY_PATH`.)

# Usage

```bash
# Aventon
.venv/bin/python scrape_aventon.py                  # all models -> aventon_ebikes.json
.venv/bin/python scrape_aventon.py --limit 3        # quick test (first 3 models)

# Lectric
.venv/bin/python scrape_lectric.py                  # all models -> lectric_ebikes.json
.venv/bin/python scrape_lectric.py --limit 2        # quick test (first 2 families)

# Ride1Up
.venv/bin/python scrape_ride1up.py                  # all models -> ride1up_ebikes.json
.venv/bin/python scrape_ride1up.py --limit 2        # quick test (first 2 models)

# Specialized
.venv/bin/python scrape_specialized.py              # all models -> specialized_ebikes.json
.venv/bin/python scrape_specialized.py --limit 3    # quick test (first 3 models)

# Velotric
.venv/bin/python scrape_velotric.py                 # all models -> velotric_ebikes.json
.venv/bin/python scrape_velotric.py --limit 3       # quick test (first 3 models)

# Heybike
.venv/bin/python scrape_heybike.py                  # all models -> heybike_ebikes.json
.venv/bin/python scrape_heybike.py --limit 3        # quick test (first 3 models)

# Mokwheel
.venv/bin/python scrape_mokwheel.py                 # all models -> mokwheel_ebikes.json
.venv/bin/python scrape_mokwheel.py --limit 3       # quick test (first 3 models)

# EVELO
.venv/bin/python scrape_evelo.py                    # all models -> evelo_ebikes.json
.venv/bin/python scrape_evelo.py --limit 2          # quick test (first 2 models)

# Tern
.venv/bin/python scrape_tern.py                     # all e-bikes -> tern_ebikes.json
.venv/bin/python scrape_tern.py --limit 3           # quick test (first 3 bike pages)

# Common flags (all): -o out.json, --concurrency N, --headed
```

# Scheduled runs (cadence)

`run_scrape.sh` is a cron-friendly wrapper that runs **all** scrapers. For each:

- runs it with the project venv,
- keeps the latest result at `<brand>_ebikes.json`,
- writes a dated snapshot to `data/current/<brand>_ebikes_YYYY-MM-DD.json`,
  rotating that brand's previous snapshot into `data/legacy/` (so `current/`
  always holds the newest per brand and `legacy/` keeps the history for diffing
  prices/specs over time),
- appends logs to `logs/scrape.log`.

One scraper failing does not stop the others. It's installed to run **weekly,
Mondays at 6:00am**:

```
0 6 * * 1  /home/bblashill/ebike-compare/run_scrape.sh
```

Manage it with `crontab -l` / `crontab -e`. Run it on demand any time with
`./run_scrape.sh`.

> **WSL caveat:** cron only runs while the WSL instance is up and the `cron`
> service has been started. WSL does not start services on boot by default, so
> after a Windows reboot you may need `sudo service cron start` (add it to your
> shell profile or enable systemd in `/etc/wsl.conf` to make it automatic).
> Verify with `pgrep -x cron`.

---

# Normalized dataset (`ebikes_normalized.json`)

`normalize.py` builds one combined, **snake_case** JSON from all the per-brand
`*_ebikes.json` files (which stay the source of truth). It's a flat array of
model documents with a uniform schema (defined in `ebikes.schema.json`),
intended to be loaded into a React app and searched/filtered/grouped client-side
(e.g. with Orama).

Each model is keyed by a unique `id` (`brand__source_id`) and unifies the
per-brand differences: `model` (from model/title), `price`/`price_min`/`price_max`
(from price_from or price_range or the configurations), `configurations` (Lectric
`configs` folded in), with brand-specific fields preserved under `brand_extra`.

**Grouped specs.** The normalized `specs` is `{ all, grouped }` — `all` is the flat
searchable label→value map; `grouped` reorganizes it into ordered, Aventon-style
sections (`spec_groups.py`): **General Info, Ebike System, Special Features, Safety,
Certifications, Water Resistance, Frameset, Drivetrain, Brakes, Wheelset, Cockpit,
Geometry, Included Accessories, General / Other**. The taxonomy follows Aventon's real
PDP sections, extended with Safety / Certifications / Water Resistance / Special
Features (regen, radar, app, anti-theft, walk mode…). The **Geometry** group is the
model's `geometry` field (the Aventon geometry-data set from `add_geometry.py`).
(The raw per-brand `physical`/`technical` split is not carried into the normalized
doc — `grouped` replaces it.)

**Options under the model.** `available_options` lists only real options for that
model. **Color is an option only when it raises the price** (otherwise colors are a
visual attribute under `colors`); single forced choices (e.g. "One Size") are dropped.
Generic, brand-wide accessories stay at the brand level in `brands[].available_accessories`.

**Discounts & freebies.** `pricing` = `{ price, regular_price, on_sale,
discount_amount, discount_pct }` — `add_pricing.py` reads each Shopify catalog's
`compare_at_price` to detect sales (e.g. Lectric XP4 $999 vs $1078 → 7% off).
`included_accessories` lists the $0 items that come bundled with the bike.

```bash
.venv/bin/python add_pricing.py      # regular/compare-at price -> discount detection
.venv/bin/python normalize.py        # -> ebikes_normalized.json (grouped specs, pricing)
```

---

# Analysis layer (`analyze.py`)

The scraped specs are **free-text** (`"Up to 60 miles"`, `"105 N·m"`, `"32.5 kg /
71.6lbs"`, `"Lifetime Warranty"`) — you can't sort, filter, or compare on them. The
site's job is to let consumers compare features and value, and different shoppers
prioritize different things (range, hill-climbing torque, warranty, component
quality, price). So `analyze.py` reads `ebikes_normalized.json` (plus the BOM
estimates in `component_cost_estimates.json`), compares every model against the whole
field, and writes an `analysis` block back into each model — in **two tiers**:

### Tier 1 — `specs_typed` (primary searchable data)

Predictable, **unit-fixed** fields parsed out of the free text. Every field has one
fixed type and one fixed unit, baked into its name and identical across all models,
so the React/Orama layer can range-query directly (e.g. `range_mi ≥ 50 AND torque_nm
≥ 75 AND price ≤ 2000`). A value is `null` when not found — **never coerced to 0**, so
a bike is neither penalized nor wrongly matched for an un-scraped spec.

| Field | Unit / type | Notes |
|-------|-------------|-------|
| `battery_wh` | int (Wh) | direct Wh, else V×Ah; dual-battery bikes may state a combined total |
| `cell_brand` | string | samsung / lg / panasonic / generic |
| `removable_battery` | bool | |
| `motor_w` | int (W) | continuous (not peak) |
| `motor_peak_w` | int (W) | peak power |
| `torque_nm` | int (Nm) | |
| `drive_type` | enum | `hub` / `mid` |
| `range_mi` | int (miles) | max of a claimed range |
| `weight_lb` | float (lb) | bike weight (kg auto-converted; rider/payload rows ignored) |
| `brake_type` | enum | hydraulic_disc / mechanical_disc / disc / rim |
| `drivetrain_type` | enum | belt / internal_gear / derailleur / single_speed |
| `gears` | int | |
| `suspension` | enum | full / air_fork / coil_fork / rigid |
| `frame_material` | enum | carbon / aluminum / steel |
| `sensor_type` | enum | torque / cadence |
| `display_type` | enum | color_tft / lcd / basic |
| `water_resistance` | string | IP rating (e.g. IPX7) |
| `ul_listed` | bool | UL 2271 / 2849 / 2580 present |
| `warranty_years` | int | `99` = lifetime |
| `connectivity` | string[] | app / gps / bluetooth / alarm |
| `notable_tech` | string[] | regen braking, ABS, belt drive, dual-battery, anti-theft, … |

### Tier 2 — value-added "vs the field" metrics (a quick compare aid only)

- **`percentiles`** — for each numeric field, its rank within the field, `0..1`
  (`battery_wh_pct: 0.85` = bigger battery than 85% of bikes). `weight_lb` and `price`
  are inverted, so lighter / cheaper rank higher.
- **`scores`** — independent **0–100** per dimension: `power`, `range`, `battery`
  (numeric, = the field-relative position), `components`, `safety`, `security`, `tech`
  (categorical, from transparent additive rubrics), `warranty` (years → score), and
  `value` (BOM share of retail, blended with price rank). `null` when un-scoreable.
- **`highlights`** — notable features surfaced for the UI.

There is **deliberately no composite/overall score** — a single blended number would
bake in subjective weights. Every typed field and dimension stands alone so the user
chooses what matters and the site ranks on *their* criteria. The dataset also carries
a top-level **`analysis_stats`** (per-field `{min, p10, p50, p90, max, count}`) — the
baseline the percentiles are measured against, and handy for "top 10%"-style UI.

```bash
# Order matters: needs the normalized file and the component-cost estimates.
.venv/bin/python estimate_component_costs.py
.venv/bin/python normalize.py
.venv/bin/python analyze.py          # enriches ebikes_normalized.json in place
```

`run_scrape.sh` runs all three at the end of every scheduled scrape.
