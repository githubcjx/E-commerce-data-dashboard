<script setup>
import { computed } from "vue";
import TrendChart from "./TrendChart.vue";
import { useDashboardStore } from "../stores/dashboard";

const props = defineProps({
  activeKey: String,
  metricDefs: Array,
  points: Array,
});
const emit = defineEmits(["active", "drag-handle-armed"]);

const store = useDashboardStore();
const def = computed(() =>
  props.metricDefs?.find((m) => m.key === props.activeKey) ||
  props.metricDefs?.[0] ||
  { key: "sales", label: "销售额", format: "currency" }
);

const granularityLabel = computed(() => ({
  day: "日K", week: "周K", month: "月K", year: "年K",
}[store.trendGranularity || store.granularity] || ""));
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">{{ def.label }}</span>
      <span class="panel-subtitle">{{ granularityLabel }} 趋势 · 拖动底部滚动条或鼠标滚轮缩放</span>
      <div class="panel-actions">
        <slot name="handle" />
      </div>
    </header>
    <div class="panel-body">
      <div class="chip-row">
        <button
          v-for="m in metricDefs"
          :key="m.key"
          :class="['chip', { 'is-active': m.key === activeKey }]"
          @click="emit('active', m.key)"
        >{{ m.label }}</button>
      </div>
      <TrendChart
        :points="points"
        :format="def.format"
        :label="def.label"
        :granularity="store.trendGranularity || store.granularity"
      />
    </div>
  </section>
</template>
