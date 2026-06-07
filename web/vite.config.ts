import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so the static build works under any host path.
export default defineConfig({
  base: "./",
  plugins: [react()],
});
