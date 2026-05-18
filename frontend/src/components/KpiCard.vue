<script setup>
import { computed } from "vue";
import { formatValue, formatDelta } from "../utils/format";
import Sparkline from "./Sparkline.vue";
import GripIcon from "./GripIcon.vue";

const props = defineProps({
  item: { type: Object, required: true },
  isActive: Boolean,
  dragState: { type: String, default: null }, // "dragging" | "over" | null
});
const emit = defineEmits(["click", "dragstart", "dragenter", "dragover", "dragleave", "drop", "dragend"]);

const delta = computed(() => {
  const it = props.item;
  if (it.delta_pct === null || it.delta_pct === undefined) {
    return { sign: "flat", text: "—", arrow: "→" };
  }
  // Reuse formatDelta logic from raw values
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
      <div class="metric-prev">上期 {{ formatValue(item.prev, item.format) }}</div>
    </div>
    <Sparkline :values="item.series || []" :trend="delta.sign" />
  </div>
</template>
