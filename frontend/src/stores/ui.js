import { defineStore } from "pinia";

const DEFAULT_TOAST_MS = 2400;

export const useUiStore = defineStore("ui", {
  state: () => ({
    isDragging: false,
    toast: null,
  }),
  actions: {
    setDragging(v) { this.isDragging = v; },
    // Optional 3rd arg `durationMs` lets important toasts (e.g. rollback
    // confirmation with row count) stay visible long enough to read.
    showToast(msg, kind = "success", durationMs = DEFAULT_TOAST_MS) {
      const id = Date.now() + Math.random();
      this.toast = { msg, kind, id };
      setTimeout(() => {
        // Only clear if no newer toast has replaced this one.
        if (this.toast && this.toast.id === id) this.toast = null;
      }, durationMs);
    },
  },
});
