import { defineConfig } from "vite";

// Stage 0b: Vite is the frontend build tool. Source stays in static/ (root), so the whole
// module graph is unchanged from the native-ESM Stage 0a — Vite just bundles + content-hashes it.
//   dev  (npm run dev)   → Vite dev server on :5173 with HMR; proxies Flask-owned paths to :8000
//   build(npm run build) → dist/index.html + dist/assets/*.[hash].{js,css,woff2}, served by Flask
export default defineConfig({
  root: "static",              // static/index.html is the entry (imports app.js → scaler/ingredient-row; links styles.css)
  base: "/",                   // built assets referenced as /assets/… (Flask serves them at that path)
  build: {
    outDir: "../dist",         // repo-root dist/ (gitignored, built on deploy)
    emptyOutDir: true,
  },
  server: {
    // The client hits these on the Flask origin; in dev the app loads from Vite (:5173), so these
    // MUST proxy to Flask or they 404. /fonts is kept as a safety net even though CSS-referenced
    // fonts are normally resolved/bundled by Vite itself.
    proxy: {
      "/api": "http://localhost:8000",
      "/images": "http://localhost:8000",
      "/fonts": "http://localhost:8000",
    },
  },
});
