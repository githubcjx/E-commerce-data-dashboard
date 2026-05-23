<script setup>
import { computed } from "vue";
import { formatValue, formatDelta } from "../utils/format";
import Sparkline from "./Sparkline.vue";
import GripIcon from "./GripIcon.vue";
import { useDashboardStore } from "../stores/dashboard";

const props = defineProps({
  item: { type: Object, required: true },
  isActive: Boolean,
  dragState: { type: String, default: null }, // "dragging" | "over" | null
});
const emit = defineEmits(["click", "dragstart", "dragenter", "dragover", "dragleave", "drop", "dragend"]);

const store = useDashboardStore();

const delta = computed(() => {
  const it = props.item;
  if (it.delta_pct === null || it.delta_pct === undefined) {
    return { sign: "flat", text: "—", arrow: "→" };
  }
  return formatDelta(it.value, it.prev, it.higher_is_better);
});

const cls = computed(() => [
  "metric-card",
  props.isActive ? "is-active" : "",
  props.dragState === "dragging" ? "is-dragging" : "",
  props.dragState === "over" ? "is-drop-target" : "",
].filter(Boolean));
</script>

<template>
  <div
    :class="cls"
    draggable="true"
    role="button"
    tabindex="0"
    @click="emit('click')"
    @dragstart="emit('dragstart', $event)"
    @dragenter="emit('dragenter', $event)"
    @dragover="emit('dragover', $event)"
    @dragleave="emit('dragleave', $event)"
    @drop="emit('drop', $event)"
    @dragend="emit('dragend', $event)"
  >
    <div>
      <div class="metric-head">
        <span class="metric-label">{{ item.label }}</span>
        <span class="metric-handle" title="拖动调整位置"><GripIcon /></span>
      </div>
      <div class="metric-value-row">
        <span class="metric-value">{{ formatValue(item.value, item.format) }}</span>
        <span :class="['metric-delta', delta.sign]">
          {{ delta.arrow }}{{ delta.text === "—" ? "" : delta.text }}
        </span>
      </div>
      <div class="metric-prev" :title="store.previousLabel">
        对比 {{ store.previousLabel || "上期" }} · {{ formatValue(item.prev, item.format) }}
      </div>
    </div>
    <Sparkline :values="item.series || []" :trend="delta.sign" />
  </div>
</template>

<style scoped>
.rate-toggle {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: auto; padding: 2px 6px 2px 4px;
  border: 1px solid var(--border); border-radius: 999px;
  background: var(--surface); cursor: pointer; user-select: none;
  font-size: 10px; color: var(--ink-3);
}
.rate-toggle:hover { border-color: var(--ink-5); }
.rate-toggle-track {
  width: 22px; height: 12px; border-radius: 999px;
  background: var(--divider); position: relative;
  transition: background 0.15s;
}
.rate-toggle-track.on { background: var(--accent); }
.rate-toggle-thumb {
  position: absolute; top: 1px; left: 1px;
  width: 10px; height: 10px; border-radius: 999px; background: #fff;
  transition: left 0.15s;
}
.rate-toggle-track.on .rate-toggle-thumb { left: 11px; }
.rate-toggle-text { font-family: var(--font-mono); font-size: 10px; line-height: 1; }
</style>
