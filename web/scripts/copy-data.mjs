// Copies the normalized dataset into public/ so the static app can fetch it.
//
// Guard: the weekly scrape cron (run_scrape.sh) wipes + re-scrapes the per-brand
// files, and if it is interrupted partway, normalize.py emits a TRUNCATED active
// dataset (far fewer models/brands). rebuild_offline.sh / run_scrape.sh gate
// promotion on validate_build.py, but this copy runs from predev/prebuild and
// must not blindly overwrite a good public/ build with a truncated active. So we
// refuse to copy when the source has dramatically fewer models than the dataset
// already in public/ (recover from data/legacy/<date>/ instead). Override with
// FORCE_COPY_DATA=1 for an intentional shrink.
import { copyFileSync, mkdirSync, existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../data/current/active/ebikes_normalized.json");
const dest = resolve(here, "../public/ebikes_normalized.json");

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
copyFileSync(src, dest);
console.log(`[copy-data] ${src} -> ${dest} (${srcN} models)`);
