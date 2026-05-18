<script setup>
import { ref } from "vue";
import KpiCard from "./KpiCard.vue";
import { useUiStore } from "../stores/ui";

const props = defineProps({
  order: { type: Array, required: true },
  items: { type: Array, required: true }, // KPI items keyed by .key
  activeKey: { type: String, required: true },
});
const emit = defineEmits(["update:order", "active"]);

const ui = useUiStore();
const dragIndex = ref(null);
const overIndex = ref(null);

const byKey = (k) => props.items.find((it) => it.key === k);

function onStart(i, e) {
  dragIndex.value = i;
  e.dataTransfer.effectAllowed = "move";
  try { e.dataTransfer.setData("text/plain", String(i)); } catch (_) {}
  ui.setDragging(true);
}
function onEnter(i, e) {
  e.preventDefault();
  if (dragIndex.value === null || dragIndex.value === i) return;
  overIndex.value = i;
}
function onOver(_i, e) {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
}
function onDrop(i, e) {
  e.preventDefault();
  const from = dragIndex.value;
  if (from === null || from === i) return reset();
  const next = props.order.slice();
  const [moved] = next.splice(from, 1);
  next.splice(i, 0, moved);
  emit("update:order", next);
  reset();
}
function reset() {
  dragIndex.value = null;
  overIndex.value = null;
  ui.setDragging(false);
}

function stateFor(i) {
  if (dragIndex.value === i) return "dragging";
  if (overIndex.value === i && dragIndex.value !== null) return "over";
  return null;
}
</script>

<template>
  <div class="metrics-grid">
    <KpiCard
      v-for="(key, i) in order"
      :key="key"
      :item="byKey(key) || { key, label: key, value: 0, prev: 0, format: 'currency', higher_is_better: true, series: [] }"
      :is-active="activeKey === key"
      :drag-state="stateFor(i)"
      @click="emit('active', key)"
      @dragstart="onStart(i, $event)"
      @dragenter="onEnter(i, $event)"
      @dragover="onOver(i, $event)"
      @drop="onDrop(i, $event)"
      @dragend="reset"
    />
  </div>
</template>
