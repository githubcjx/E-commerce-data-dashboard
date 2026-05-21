<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent,
  DataZoomComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

echarts.use([
  LineChart, GridComponent, TooltipComponent, MarkLineComponent,
  MarkAreaComponent, DataZoomComponent, CanvasRenderer,
]);

const props = defineProps({
  points: { type: Array, required: true }, // [{date, value}]
  format: { type: String, default: "currency" },
  label: { type: String, default: "" },
  granularity: { type: String, default: "day" }, // day | week | month | year
  // Highlight overlay — the user's top filter range. We mark this stretch
  // visually on the chart and pan the dataZoom to keep it in view.
  highlightStart: { type: String, default: "" }, // ISO date
  highlightEnd:   { type: String, default: "" }, // ISO date
});

const el = ref(null);
let chart = null;

// Default visible window sized per granularity (used only when no highlight
// is provided, e.g. before the user has touched the top filter).
const DEFAULT_WINDOW = { day: 30, week: 12, month: 12, year: 5 };

function fmt(v) {
  if (v === null || v === undefined) return "—";
  if (props.format === "percent") return Number(v).toFixed(2) + "%";
  if (props.format === "int") return Math.round(Number(v)).toLocaleString("en-US");
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ---------------------------------------------------------------------------
// Bucket-label parsing: turn a label into [startDate, endDate] (ISO strings)
// so we can overlap-test against the user's highlight range.
// ---------------------------------------------------------------------------
function bucketBounds(label, gran) {
  if (gran === "day") return [label, label];
  if (gran === "week") {
    const [s, e] = label.split("~");
    return [s, e];
  }
  if (gran === "month") {
    const [y, m] = label.split("-").map(Number);
    const last = new Date(y, m, 0).getDate();
    const mm = String(m).padStart(2, "0");
    return [`${y}-${mm}-01`, `${y}-${mm}-${String(last).padStart(2, "0")}`];
  }
  if (gran === "year") {
    return [`${label}-01-01`, `${label}-12-31`];
  }
  return [label, label];
}

// Index range of buckets that overlap [highlightStart, highlightEnd].
// Returns null when no highlight or no overlap.
const highlightIdx = computed(() => {
  const { highlightStart: hs, highlightEnd: he, points, granularity } = props;
  if (!hs || !he || !points.length) return null;
  let first = -1, last = -1;
  for (let i = 0; i < points.length; i++) {
    const [bs, be] = bucketBounds(points[i].date, granularity);
    // overlap test on ISO strings (lexicographic == chronological for YYYY-MM-DD)
    if (bs <= he && be >= hs) {
      if (first === -1) first = i;
      last = i;
    }
  }
  if (first === -1) return null;
  return { first, last };
});

// Recompute dataZoom start/end so the highlight is centered in view.
// Falls back to "show latest N buckets" when there's no highlight.
function computeDataZoom() {
  const n = props.points.length;
  if (n <= 1) return { start: 0, end: 100 };
  const window = DEFAULT_WINDOW[props.granularity] || 30;
  const hr = highlightIdx.value;
  if (!hr) {
    if (n <= window) return { start: 0, end: 100 };
    const start = ((n - window) / (n - 1)) * 100;
    return { start, end: 100 };
  }
  // Want at least DEFAULT_WINDOW worth of context around the highlighted span.
  const span = hr.last - hr.first + 1;
  const visible = Math.max(window, span + 4);
  const center = (hr.first + hr.last) / 2;
  let left = center - visible / 2;
  let right = center + visible / 2;
  if (left < 0) { right -= left; left = 0; }
  if (right > n - 1) { left -= (right - (n - 1)); right = n - 1; }
  left = Math.max(0, left);
  return {
    start: (left / (n - 1)) * 100,
    end: (right / (n - 1)) * 100,
  };
}

const seriesData = computed(() => {
  const hr = highlightIdx.value;
  return props.points.map((p, i) => {
    const lit = hr && i >= hr.first && i <= hr.last;
    if (!lit) return p.value;
    // Highlighted dot: bigger + red (Chinese stock gain color)
    return {
      value: p.value,
      symbolSize: 11,
      itemStyle: {
        color: "var(--gain)",
        borderColor: "var(--gain)",
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: "rgba(220, 60, 50, 0.45)",
      },
    };
  });
});

const markArea = computed(() => {
  const hr = highlightIdx.value;
  // Always return a markArea object so partial setOption() updates can clear
  // an existing highlight by passing an empty data array.
  const base = {
    silent: true,
    itemStyle: { color: "rgba(220, 60, 50, 0.08)", borderColor: "rgba(220, 60, 50, 0.25)", borderWidth: 1 },
    data: [],
  };
  if (!hr) return base;
  return {
    ...base,
    data: [[{ xAxis: props.points[hr.first].date }, { xAxis: props.points[hr.last].date }]],
  };
});

const option = computed(() => {
  const zoom = computeDataZoom();
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
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: 0,
        start: zoom.start,
        end: zoom.end,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
      },
      {
        type: "slider",
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
        data: seriesData.value,
        markLine: {
          silent: true,
          symbol: "none",
          lineStyle: { color: "#D4D2CA", width: 1 },
          data: [{ yAxis: 0 }],
          label: { show: false },
        },
        markArea: markArea.value,
      },
    ],
  };
});

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

// Full rebuild on points/granularity change — these reshape the axis.
watch([() => props.points, () => props.granularity], () => {
  if (chart) chart.setOption(option.value, true);
});

// Highlight-only change: don't blow away the chart, just patch the series
// + markArea + smooth-pan the dataZoom to the new center.
watch([() => props.highlightStart, () => props.highlightEnd], () => {
  if (!chart) return;
  const zoom = computeDataZoom();
  chart.setOption({
    series: [{
      data: seriesData.value,
      markArea: markArea.value,
    }],
    dataZoom: [
      { start: zoom.start, end: zoom.end },
      { start: zoom.start, end: zoom.end },
    ],
  });
});
</script>

<template>
  <div class="trend-wrap">
    <div ref="el" class="trend-chart"></div>
  </div>
</template>
