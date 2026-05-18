<script setup>
import { computed } from "vue";
import TrendChart from "./TrendChart.vue";

const props = defineProps({
  activeKey: String,
  metricDefs: Array,
  points: Array,
});
const emit = defineEmits(["active", "drag-handle-armed"]);

const def = computed(() => props.metricDefs?.find((m) => m.key === props.activeKey) || props.metricDefs?.[0] || { key: "sales", label: "销售额", format: "currency" });
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">{{ def.label }}</span>
      <span class="panel-subtitle">趋势</span>
      <div class="panel-actions">
        <button class="btn ghost sm">导出</button>
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
      <TrendChart :points="points" :format="def.format" :label="def.label" />
    </div>
  </section>
</template>
