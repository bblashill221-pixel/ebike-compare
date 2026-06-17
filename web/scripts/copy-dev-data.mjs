// DEV-ONLY data copy: makes the anomaly-audit report available to the dev server.
//
// Run from `predev` only (NOT `prebuild`), so anomalies.json lands in public/ for
// `npm run dev` but is never bundled into the production `dist/`. Combined with
// the QA route being gated behind import.meta.env.DEV, the QA page and its data
// exist only during development.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../data/current/anomalies.json");
const dest = resolve(here, "../public/anomalies.json");

if (!existsSync(src)) {
  console.log(`[copy-dev-data] no anomalies.json yet (run audit_anomalies.py) — skipping`);
  process.exit(0);
}
mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`[copy-dev-data] ${src} -> ${dest}`);
