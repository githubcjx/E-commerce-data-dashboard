import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import fs from "node:fs";
import path from "node:path";

// Build timestamp = build version. Baked into the JS bundle via
// import.meta.env.VITE_APP_VERSION and also written to dist/version.json so
// the running page can poll for a new deploy and notify the user to refresh.
const APP_VERSION = String(Date.now());
process.env.VITE_APP_VERSION = APP_VERSION;

// Tiny plugin: drop dist/version.json after the build so /version.json is a
// real static asset Nginx can serve.
function emitVersionJson() {
  return {
    name: "emit-version-json",
    apply: "build",
    closeBundle() {
      const out = path.resolve(__dirname, "dist", "version.json");
      fs.mkdirSync(path.dirname(out), { recursive: true });
      fs.writeFileSync(out, JSON.stringify({ version: APP_VERSION }) + "\n");
    },
  };
}

export default defineConfig({
  plugins: [vue(), emitVersionJson()],
  server: {
    port: 9586,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
