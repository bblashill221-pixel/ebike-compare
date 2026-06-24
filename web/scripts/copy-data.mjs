// Produces public/ebike.json — the dataset the static app fetches.
//
// This runs the SLIM web build (slim_web_build.py): it drops fields the web never
// reads and INTERNS repeated spec values into a shared `specs_values` table, so the
// served file is ~60% smaller than the full internal build and the app shares one
// object per unique component. (A plain copy of the full active file would defeat
// that interning — which is exactly the regression this script previously caused by
// overwriting the slim build promoted by rebuild_offline.sh.)
//
// Guard: the weekly scrape cron (run_scrape.sh) wipes + re-scrapes the per-brand
// files, and if it is interrupted partway, normalize.py emits a TRUNCATED active
// dataset (far fewer models/brands). rebuild_offline.sh / run_scrape.sh gate
// promotion on validate_build.py, but this copy runs from predev/prebuild and must
// not blindly overwrite a good public/ build with a truncated active. So we refuse
// when the source has dramatically fewer models than the dataset already in public/
// (recover from data/legacy/<date>/ instead). Override with FORCE_COPY_DATA=1.
import { copyFileSync, mkdirSync, existsSync, readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const src = resolve(repo, "data/current/active/ebike.json");
const dest = resolve(here, "../public/ebike.json");
const slimScript = resolve(repo, "slim_web_build.py");

if (!existsSync(src)) {
  console.error(`[copy-data] source not found: ${src}`);
  process.exit(1);
}

const modelCount = (p) => {
  try {
    const d = JSON.parse(readFileSync(p, "utf8"));
    return d.model_count ?? (Array.isArray(d.models) ? d.models.length : 0);
  } catch {
    return null;
  }
};

const srcN = modelCount(src);
if (srcN === null || srcN === 0) {
  console.error(`[copy-data] refusing: source is unreadable or has 0 models (${src})`);
  process.exit(1);
}

// Only guard against shrinkage relative to an existing good public/ build.
const SHRINK_FLOOR = 0.9; // allow up to 10% fewer (normal churn); block a collapse
if (existsSync(dest) && !process.env.FORCE_COPY_DATA) {
  const destN = modelCount(dest);
  if (destN && srcN < destN * SHRINK_FLOOR) {
    console.error(
      `[copy-data] REFUSING to overwrite public/ — source has ${srcN} models vs ` +
        `${destN} already published (a ${Math.round((1 - srcN / destN) * 100)}% drop).\n` +
        `  This usually means a scrape was interrupted and active/ is truncated.\n` +
        `  Recover: restore data/current/ from the latest data/legacy/<date>/ snapshot, then ./rebuild_offline.sh\n` +
        `  Override (intentional shrink): FORCE_COPY_DATA=1 npm run <cmd>`
    );
    process.exit(1);
  }
}

mkdirSync(dirname(dest), { recursive: true });

// Prefer the project venv's python (the pipeline's interpreter), else PATH python3.
const venvPy = resolve(repo, ".venv/bin/python");
const pythonBin = existsSync(venvPy) ? venvPy : "python3";

let slimmed = false;
if (existsSync(slimScript)) {
  const r = spawnSync(pythonBin, [slimScript, "-i", src, "-o", dest], {
    stdio: ["ignore", "inherit", "inherit"],
  });
  slimmed = r.status === 0;
  if (!slimmed) {
    console.warn(
      `[copy-data] slim build failed (python: ${pythonBin}, status ${r.status ?? r.error?.code}); ` +
        `falling back to a full-file copy — the served file will be larger and un-interned.`
    );
  }
}

if (!slimmed) {
  // Fallback: serve the full file so the app still works (no specs_values interning).
  copyFileSync(src, dest);
  console.log(`[copy-data] ${src} -> ${dest} (${srcN} models, FULL/un-slimmed)`);
}

// The QA anomaly report ships in every build now (dev + prod): the /qa page is
// reachable in production behind a client-side gate (localStorage `qa`). NOTE this
// makes anomalies.json publicly fetchable — the gate hides only the page UI.
const qaSrc = resolve(repo, "data/current/anomalies.json");
const qaDest = resolve(here, "../public/anomalies.json");
if (existsSync(qaSrc)) {
  copyFileSync(qaSrc, qaDest);
  console.log(`[copy-data] ${qaSrc} -> ${qaDest}`);
} else {
  console.log(`[copy-data] no anomalies.json yet (run audit_anomalies.py) — skipping`);
}
