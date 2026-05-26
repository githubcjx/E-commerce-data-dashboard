<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent, TooltipComponent, MarkLineComponent, DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { formatCurrency } from "../utils/format";

echarts.use([
  LineChart, GridComponent, TooltipComponent, MarkLineComponent,
  DataZoomComponent, CanvasRenderer,
]);

const props = defineProps({
  points: { type: Array, required: true }, // [{date, value}]
  format: { type: String, default: "currency" },
  label: { type: String, default: "" },
});

const el = ref(null);
let chart = null;

// Tooltip values use the same currency formatter as everywhere else, so
// ≥10万 collapses to "X.XX万" and the tooltip stays compact.
function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (props.format === "percent") return Number(v).toFixed(2) + "%";
  if (props.format === "int") return Math.round(Number(v)).toLocaleString("en-US");
  return formatCurrency(v);
}

// Y-axis labels mirror the same currency rule as KPI cards/tooltip: ≥10万
// collapses to "X.XX万", smaller values stay in full thousands-separator
// form. Keeps axis labels compact for large-revenue tenants.
function yAxisLabel(v) {
  if (props.format === "percent") return v.toFixed(0) + "%";
  if (props.format === "int") return Math.round(v).toLocaleString("en-US");
  const n = Number(v);
  if (Math.abs(n) >= 100000) {
    return (n / 10000).toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + "万";
  }
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

const option = computed(() => ({
  // Left padding tuned for "X.XX万" style labels (≥10万 collapses); leaves
  // a bit of headroom for occasional "1,234.56万" widths.
  grid: { left: 64, right: 24, top: 16, bottom: 56 },
  xAxis: {
    type: "category",
    data: props.points.map((p) => p.date),
    boundaryGap: false,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: "#97968B", fontFamily: "JetBrains Mono, monospace", fontSize: 11,
      hideOverlap: true,
    },
  },
  yAxis: {
    type: "value",
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: "#EFEDE6", type: "dashed" } },
    axisLabel: {
      color: "#97968B", fontFamily: "JetBrains Mono, monospace", fontSize: 11,
      formatter: yAxisLabel,
    },
  },
  tooltip: {
    trigger: "axis",
    backgroundColor: "#14140F",
    borderWidth: 0,
    padding: [8, 12],
    textStyle: { color: "#fff", fontFamily: "JetBrains Mono, monospace", fontSize: 12 },
    formatter: (params) => {
      const p = params[0];
      return `<div style="color:#BDBCB1;font-size:10.5px;letter-spacing:0.04em;text-transform:uppercase;margin-bottom:2px;">${props.label} · ${p.axisValue}</div><strong>${fmt(p.value)}</strong>`;
    },
  },
  // Keep the slider + inside zoom so the user can pan/zoom when the range
  // they picked happens to contain many points (e.g. 年 tab covering a
  // 3-year span on monthly bucketing).
  dataZoom: [
    {
      type: "inside",
      xAxisIndex: 0,
      start: 0, end: 100,
      zoomOnMouseWheel: true,
      moveOnMouseMove: true,
      moveOnMouseWheel: false,
    },
    {
      type: "slider",
      xAxisIndex: 0,
      start: 0, end: 100,
      height: 18,
      bottom: 8,
      borderColor: "transparent",
      backgroundColor: "#F4F2EB",
      fillerColor: "rgba(79, 93, 214, 0.18)",
      handleStyle: { color: "#4F5DD6" },
      moveHandleStyle: { color: "#4F5DD6" },
      textStyle: { color: "#97968B", fontSize: 10 },
      showDataShadow: true,
    },
  ],
  series: [
    {
      type: "line",
      smooth: 0.4,
      symbol: "circle",
      symbolSize: 6,
      itemStyle: { color: "#fff", borderColor: "#4F5DD6", borderWidth: 2 },
      lineStyle: { color: "#4F5DD6", width: 2 },
      areaStyle: {
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: "rgba(79, 93, 214, 0.18)" },
            { offset: 1, color: "rgba(79, 93, 214, 0)" },
          ],
        },
      },
      data: props.points.map((p) => p.value),
      markLine: {
        silent: true,
        symbol: "none",
        lineStyle: { color: "#D4D2CA", width: 1 },
        data: [{ yAxis: 0 }],
        label: { show: false },
      },
    },
  ],
}));

onMounted(() => {
  chart = echarts.init(el.value);
  chart.setOption(option.value, true);
  const ro = new ResizeObserver(() => chart && chart.resize());
  ro.observe(el.value);
  el.value.__ro = ro;
});

onBeforeUnmount(() => {
  el.value?.__ro?.disconnect();
  chart?.dispose();
  chart = null;
});

// Reset dataZoom on every data refresh so the user always sees the full
// selected range first (they can still pan/zoom afterwards).
watch(() => props.points, () => {
  if (chart) chart.setOption(option.value, true);
});
</script>

<template>
  <div class="trend-wrap">
    <div ref="el" class="trend-chart"></div>
  </div>
</template>
