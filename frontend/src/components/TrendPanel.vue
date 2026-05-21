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

// Trend-chart bucketing — controls *only* the chart below, not the global
// filter. Same idea as K-line "日/周/月/年" toggles on stock charts.
const granularities = [
  ["day", "日"],
  ["week", "周"],
  ["month", "月"],
  ["year", "年"],
];

function onGranularity(k) {
  if (store.trendGranularity === k) return;
  store.setTrendGranularity(k);
}

// Subtitle: chart's own range + a hint that the red overlay reflects the
// top filter selection. Range is fixed once trendGranularity is chosen.
const subtitle = computed(() => {
  const g = store.trendGranularityServed || store.trendGranularity;
  const [s, e] = store.trendRangeServed || ["", ""];
  if (!s || !e) return "拖动底部滑块或鼠标滚轮缩放";
  const range = g === "year" ? `${s.slice(0, 4)}–${e.slice(0, 4)}` : `${s} ~ ${e}`;
  return `${range} · 红色区域 = 顶部筛选所选范围`;
});
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">{{ def.label }} 趋势</span>
      <span class="panel-subtitle">{{ subtitle }}</span>
      <div class="panel-actions">
        <div class="seg" role="tablist">
          <button
            v-for="[k, l] in granularities" :key="k"
            :class="['seg-btn', { 'is-active': store.trendGranularity === k }]"
            @click="onGranularity(k)"
          >{{ l }}</button>
        </div>
        <slot name="handle" />
      </div>
    </header>
    <div class="panel-body">
      <TrendChart
        :points="points"
        :format="def.format"
        :label="def.label"
        :granularity="store.trendGranularityServed || store.trendGranularity"
        :highlight-start="store.startDate"
        :highlight-end="store.endDate"
      />
    </div>
  </section>
</template>
