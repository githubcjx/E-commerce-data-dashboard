import { defineStore } from "pinia";
import { fetchReminder } from "../api/targets";
import { hasToken } from "../api/client";

// Poll cadence for the 月末提醒. 10 min is plenty — it only flips state once
// a day at most. Mirrors the version-store polling shape.
const POLL_INTERVAL_MS = 10 * 60 * 1000;
const INITIAL_DELAY_MS = 4 * 1000;

let pollTimer = null;
let started = false;

export const useTargetReminderStore = defineStore("targetReminder", {
  state: () => ({
    shouldRemind: false,
    yearMonth: null,
    missingCount: 0,
    missingOwners: [],
    dismissed: false, // closed for this session
  }),
  getters: {
    visible: (s) => s.shouldRemind && !s.dismissed,
  },
  actions: {
    async check() {
      if (!hasToken()) return; // logged out — don't poll
      try {
        const data = await fetchReminder();
        this.shouldRemind = !!data.should_remind;
        this.yearMonth = data.year_month || null;
        this.missingCount = data.missing_count || 0;
        this.missingOwners = data.missing_owners || [];
      } catch (_) {
        /* transient / not permitted — stay quiet, retry next tick */
      }
    },
    // Idempotent — safe to call again once the user role is known.
    start() {
      if (started) return;
      started = true;
      setTimeout(() => this.check(), INITIAL_DELAY_MS);
      pollTimer = setInterval(() => this.check(), POLL_INTERVAL_MS);
    },
    dismiss() {
      this.dismissed = true;
    },
  },
});
