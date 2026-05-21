import { defineStore } from "pinia";

// Build version baked in at compile time (see vite.config.js).
// In `vite dev` (no build) it'll be undefined → we fall back to "dev" so
// the polling never fires a false positive locally.
const BUILD_VERSION = import.meta.env.VITE_APP_VERSION || "dev";

// Poll cadence. 5 min keeps the load trivial (one tiny static GET) while
// still surfacing a new deploy fast enough that users notice on their own.
const POLL_INTERVAL_MS = 5 * 60 * 1000;
// Tiny delay so the first check doesn't race with page mount.
const INITIAL_DELAY_MS = 5 * 1000;

let pollTimer = null;
let started = false;

export const useVersionStore = defineStore("version", {
  state: () => ({
    buildVersion: BUILD_VERSION,
    serverVersion: BUILD_VERSION,
    updateAvailable: false,
    dismissedFor: null,   // server version the user clicked "稍后" on
  }),
  actions: {
    async check() {
      // dev build → no version.json shipped, skip silently.
      if (BUILD_VERSION === "dev") return;
      try {
        // cache: "no-store" + a cache-buster — belt and suspenders so neither
        // the browser nor any intermediate cache pins an old response.
        const res = await fetch(`/version.json?t=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const v = String(data.version || "");
        if (!v) return;
        this.serverVersion = v;
        if (v !== this.buildVersion) {
          // If user already clicked "稍后" for this exact version, stay quiet.
          this.updateAvailable = v !== this.dismissedFor;
        }
      } catch (_) { /* offline or transient — try again next tick */ }
    },
    startPolling() {
      if (started || BUILD_VERSION === "dev") return;
      started = true;
      setTimeout(() => this.check(), INITIAL_DELAY_MS);
      pollTimer = setInterval(() => this.check(), POLL_INTERVAL_MS);
      // Tab regains focus → check immediately. Most updates get noticed
      // here because users often switch tabs around when admins deploy.
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) this.check();
      });
    },
    dismiss() {
      this.dismissedFor = this.serverVersion;
      this.updateAvailable = false;
    },
    reload() {
      // window.location.reload() does the right thing as long as index.html
      // is served with no-cache (see nginx.conf). Hash-named JS/CSS assets
      // are pulled fresh because index.html now points at new filenames.
      window.location.reload();
    },
  },
});
