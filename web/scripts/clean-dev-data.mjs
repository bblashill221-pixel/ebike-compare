// Removes dev-only data from public/ before a PRODUCTION build, so `vite build`
// (which copies all of public/ into dist/) can never ship it. Paired with
// copy-dev-data.mjs (predev) — run this from `prebuild`.
import { existsSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const f = resolve(here, "../public/anomalies.json");
if (existsSync(f)) {
  rmSync(f);
  console.log(`[clean-dev-data] removed ${f} (dev-only; excluded from production)`);
}
