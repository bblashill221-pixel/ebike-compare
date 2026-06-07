# ebike-compare web

A static React site that lets people **search, filter, and compare** the e-bikes in
`../data/current/active/ebikes_normalized.json`, plus a fleet-wide **analysis**
dashboard. Built with Vite + React + TypeScript + TailwindCSS; client-side search via
[Orama](https://oramasearch.com/).

## Prerequisites
A **Linux** Node (≥ 18) on `PATH`. (Inside WSL, Windows Node cannot build in the WSL
filesystem; install a Linux Node, e.g. via nvm.)

## Develop
```bash
cd web
npm install
npm run dev        # http://localhost:5173  (predev copies the JSON into public/)
```

## Build / preview
```bash
npm run build      # type-checks, copies data, outputs static site to dist/
npm run preview    # serve the production build
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
```

The dataset is copied into `public/ebikes_normalized.json` by `scripts/copy-data.mjs`
(run automatically by `predev`/`prebuild`). The copy is git-ignored; re-run
`npm run copy-data` after regenerating the dataset.

## Structure
- `src/data/DataProvider.tsx` — fetches the JSON, builds the Orama index, exposes
  models/brands/stats + facet options & range bounds.
- `src/search/orama.ts` — index schema, filtering (`where`), and facets.
- `src/affiliate/{config.ts,affiliateUrl.ts}` — **per-brand affiliate config** (codes
  are placeholders; links fall back to the plain product URL until a code is set).
- `src/pages/` — Browse, BikeDetail, Compare, Analysis, Disclosure.
- `src/components/` — cards, facets, score bars, spec/compare tables, distribution
  plots, affiliate link + disclosure badge, compare tray, header, footer.

## Notes
- **No composite score.** The UI exposes per-dimension scores (0–100) and percentiles
  and sorts/compares on individual criteria. Do not add a blended "overall" score.
- **Affiliate disclosure.** Affiliate links carry `rel="sponsored nofollow"`, show a
  small visible badge, and there is a footer line + `/disclosure` page. This is the
  conservative FTC "clear and conspicuous" floor — confirm with counsel before launch.
- Routing uses `HashRouter` so deep links work on any static host with no server config.
