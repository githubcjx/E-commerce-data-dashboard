<script setup>
import { ref } from "vue";
import GripIcon from "./GripIcon.vue";
import { useUiStore } from "../stores/ui";

const props = defineProps({
  index: Number,
  dragIdx: Number,
  overIdx: Number,
});
const emit = defineEmits(["start", "enter", "drop", "end"]);

const ui = useUiStore();
const armed = ref(false);

const isDragging = () => props.dragIdx === props.index;
const isOver = () => props.overIdx === props.index && props.dragIdx !== null && props.dragIdx !== props.index;

function onDragStart(e) {
  if (!armed.value) { e.preventDefault(); return; }
  emit("start", props.index);
  ui.setDragging(true);
  e.dataTransfer.effectAllowed = "move";
  try { e.dataTransfer.setData("text/plain", String(props.index)); } catch (_) {}
}
function onDragEnter(e) {
  e.preventDefault();
  emit("enter", props.index);
}
function onDragOver(e) { if (props.dragIdx !== null) e.preventDefault(); }
function onDrop(e) {
  e.preventDefault();
  emit("drop", props.index);
  armed.value = false;
  ui.setDragging(false);
}
function onEnd() {
  armed.value = false;
  emit("end");
  ui.setDragging(false);
}
</script>

<template>
  <div
    :class="['section-wrap', { 'is-dragging': isDragging(), 'is-over': isOver() }]"
    :draggable="armed"
    @dragstart="onDragStart"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @drop="onDrop"
    @dragend="onEnd"
  >
    <slot :handle-armed="(v) => (armed = v)">
      <button
        class="drag-handle"
        title="拖动调整面板顺序"
        aria-label="拖动调整面板顺序"
        @mousedown="armed = true"
        @mouseup="armed = false"
        @mouseleave="armed = false"
      >
        <GripIcon />
      </button>
    </slot>
  </div>
</template>
