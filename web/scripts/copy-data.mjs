// Copies the normalized dataset into public/ so the static app can fetch it.
import { copyFileSync, mkdirSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "../../data/current/active/ebikes_normalized.json");
const dest = resolve(here, "../public/ebikes_normalized.json");

if (!existsSync(src)) {
  console.error(`[copy-data] source not found: ${src}`);
  process.exit(1);
}
mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`[copy-data] ${src} -> ${dest}`);
