import { defineStore } from "pinia";

export const useUiStore = defineStore("ui", {
  state: () => ({
    isDragging: false,
    toast: null,
  }),
  actions: {
    setDragging(v) { this.isDragging = v; },
    showToast(msg, kind = "success") {
      this.toast = { msg, kind, id: Date.now() };
      setTimeout(() => { if (this.toast && this.toast.id === this.toast.id) this.toast = null; }, 2400);
    },
  },
});
