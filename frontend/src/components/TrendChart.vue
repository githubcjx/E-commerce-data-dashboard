<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent, TooltipComponent, MarkLineComponent, DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart, GridComponent, TooltipComponent, MarkLineComponent,
  DataZoomComponent, CanvasRenderer,
]);

const props = defineProps({
  points: { type: Array, required: true }, // [{date, value}]
  format: { type: String, default: "currency" },
  label: { type: String, default: "" },
  // K-line style cadence — controls default visible window
  granularity: { type: String, default: "day" }, // day | week | month | year
});

const el = ref(null);
let chart = null;

// Default visible window sized like stock K-lines
const DEFAULT_WINDOW = {
  day: 30,    // 日K → 近 30 个交易日
  week: 12,   // 周K → 近 12 周
  month: 12,  // 月K → 近 12 月
  year: 5,    // 年K → 近 5 年
};

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (props.format === "percent") return Number(v).toFixed(2) + "%";
  if (props.format === "int") return Math.round(Number(v)).toLocaleString("en-US");
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Compute the start% the dataZoom should land on so the latest N buckets
// are shown by default; user can pan/zoom from there.
function defaultZoom() {
  const n = props.points.length;
  if (n <= 1) return { start: 0, end: 100 };
  const window = DEFAULT_WINDOW[props.granularity] || 30;
  if (n <= window) return { start: 0, end: 100 };
  const start = ((n - window) / (n - 1)) * 100;
  return { start, end: 100 };
}

const option = computed(() => {
  const zoom = defaultZoom();
  return {
    grid: { left: 56, right: 24, top: 16, bottom: 56 },
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
        formatter: (v) => {
          if (props.format === "percent") return v.toFixed(0) + "%";
          if (Math.abs(v) >= 1000) return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + "k";
          return v;
        },
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
    // K-line style scroll & zoom — slider at the bottom, wheel-zoom & drag-pan inside.
    dataZoom: [
      {
        type: "inside",          // mouse wheel + drag inside the chart
        xAxisIndex: 0,
        start: zoom.start,
        end: zoom.end,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
      {
        type: "slider",          // visible scrollbar at the bottom
        xAxisIndex: 0,
        start: zoom.start,
        end: zoom.end,
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
  };
});

onMounted(() => {
  chart = echarts.init(el.value);
  // notMerge=true so dataZoom start/end reset whenever granularity changes
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

// When data or granularity changes, reset the option fully so the default
// zoom window snaps to "latest N" again.
watch(option, (v) => { chart && chart.setOption(v, true); });
</script>

<template>
  <div class="trend-wrap">
    <div ref="el" class="trend-chart"></div>
  </div>
</template>
