<script setup>
import { computed } from "vue";
import { smoothPath } from "../utils/format";

const props = defineProps({
  values: { type: Array, required: true },
  trend: { type: String, default: "flat" },
  width: { type: Number, default: 220 },
  height: { type: Number, default: 44 },
});

const gid = `sg-${Math.random().toString(36).slice(2, 8)}`;

const paths = computed(() => {
  const values = props.values || [];
  if (!values.length) return { line: "", area: "" };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const px = (i) => (i / (values.length - 1 || 1)) * (props.width - 4) + 2;
  const py = (v) => props.height - 4 - ((v - min) / span) * (props.height - 8);
  const pts = values.map((v, i) => ({ x: px(i), y: py(v) }));
  if (Math.abs(span) < 1e-9) {
    const y = props.height / 2;
    return {
      line: `M 2 ${y} L ${props.width - 2} ${y}`,
      area: `M 2 ${y} L ${props.width - 2} ${y} L ${props.width - 2} ${props.height} L 2 ${props.height} Z`,
    };
  }
  const line = smoothPath(pts);
  const area = `${line} L ${pts[pts.length - 1].x} ${props.height} L ${pts[0].x} ${props.height} Z`;
  return { line, area };
});

const color = computed(() =>
  props.trend === "up" ? "var(--pos)" :
  props.trend === "down" ? "var(--neg)" : "var(--ink-4)"
);
</script>

<template>
  <svg :viewBox="`0 0 ${width} ${height}`" width="100%" :height="height" preserveAspectRatio="none" class="metric-spark">
    <defs>
      <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" :stop-color="color" stop-opacity="0.18" />
        <stop offset="100%" :stop-color="color" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path :d="paths.area" :fill="`url(#${gid})`" />
    <path :d="paths.line" fill="none" :stroke="color" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round" />
  </svg>
</template>
