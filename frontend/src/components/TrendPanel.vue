<script setup>
import { computed } from "vue";
import TrendChart from "./TrendChart.vue";
import { useDashboardStore } from "../stores/dashboard";

const props = defineProps({
  activeKey: String,
  metricDefs: Array,
  points: Array,
});

const store = useDashboardStore();
const def = computed(() =>
  props.metricDefs?.find((m) => m.key === props.activeKey) ||
  props.metricDefs?.[0] ||
  { key: "sales", label: "销售额", format: "currency" }
);

const subtitleLabel = computed(() => ({
  day: "按日", week: "按周", month: "按月", year: "按年",
}[store.trendGranularityServed || store.topGranularity] || ""));
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">{{ def.label }} 趋势</span>
      <span class="panel-subtitle">{{ subtitleLabel }} · 与顶部时间筛选同步</span>
      <div class="panel-actions">
        <slot name="handle" />
      </div>
    </header>
    <div class="panel-body">
      <TrendChart
        :points="points"
        :format="def.format"
        :label="def.label"
      />
    </div>
  </section>
</template>
