<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, MarkLineComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([LineChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer]);

const props = defineProps({
  points: { type: Array, required: true }, // [{date, value}]
  format: { type: String, default: "currency" },
  label: { type: String, default: "" },
});

const el = ref(null);
let chart = null;

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (props.format === "percent") return Number(v).toFixed(2) + "%";
  if (props.format === "int") return Math.round(Number(v)).toLocaleString("en-US");
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const option = computed(() => ({
  grid: { left: 56, right: 24, top: 16, bottom: 36 },
  xAxis: {
    type: "category",
    data: props.points.map((p) => p.date),
    boundaryGap: false,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: "#97968B", fontFamily: "JetBrains Mono, monospace", fontSize: 11,
      interval: props.points.length > 10 ? "auto" : 0,
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
  series: [
    {
      type: "line",
      smooth: 0.4,
      symbol: "circle",
      symbolSize: 7,
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
  chart.setOption(option.value);
  const ro = new ResizeObserver(() => chart && chart.resize());
  ro.observe(el.value);
  el.value.__ro = ro;
});

onBeforeUnmount(() => {
  el.value?.__ro?.disconnect();
  chart?.dispose();
  chart = null;
});

watch(option, (v) => { chart && chart.setOption(v); });
</script>

<template>
  <div class="trend-wrap">
    <div ref="el" class="trend-chart"></div>
  </div>
</template>
