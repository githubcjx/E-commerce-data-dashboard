<script setup>
import { computed } from "vue";
import { useDashboardStore } from "../stores/dashboard";

const store = useDashboardStore();
const emit = defineEmits(["reset"]);

// K-line vibe: 日K / 周K / 月K / 年K
const granularities = [
  ["day", "日K"],
  ["week", "周K"],
  ["month", "月K"],
  ["year", "年K"],
];

const shops = computed(() => [{ code: "all", name: "全部" }, ...(store.filters.shops || [])]);
const owners = computed(() => ["all", ...(store.filters.owners || [])]);
const cats = computed(() => ["all", ...(store.filters.categories || [])]);

function ownerLabel(v) { return v === "all" ? "全部" : v; }
function catLabel(v) { return v === "all" ? "全部" : v; }

async function refresh() {
  await store.loadAll();
}

async function onGranularity(k) {
  if (store.granularity === k) return;
  store.granularity = k;
  // Adjust default window to match the typical K-line span for the new
  // granularity, but only when the user is sitting on the previous default.
  // We keep user-explicit ranges untouched (they probably just changed
  // granularity to look at a different bucketing of the same span).
  await refresh();
}

async function onShop(v) { store.shopCode = v; await refresh(); }
async function onOwner(v) { store.owner = v; await refresh(); }
async function onCat(v) { store.category = v; await refresh(); }
async function onStart(v) {
  if (!v) return;
  store.startDate = v;
  if (store.endDate < v) store.endDate = v;
  await refresh();
}
async function onEnd(v) {
  if (!v) return;
  store.endDate = v;
  if (store.startDate > v) store.startDate = v;
  await refresh();
}

// Quick-pick presets
async function preset(days) {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - (days - 1));
  store.endDate = end.toISOString().slice(0, 10);
  store.startDate = start.toISOString().slice(0, 10);
  await refresh();
}
async function presetThisMonth() {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  store.startDate = start.toISOString().slice(0, 10);
  store.endDate = today.toISOString().slice(0, 10);
  await refresh();
}
async function presetThisYear() {
  const today = new Date();
  const start = new Date(today.getFullYear(), 0, 1);
  store.startDate = start.toISOString().slice(0, 10);
  store.endDate = today.toISOString().slice(0, 10);
  await refresh();
}
</script>

<template>
  <div class="filter-row">
    <div class="seg" role="tablist">
      <button
        v-for="[k, l] in granularities" :key="k"
        :class="['seg-btn', { 'is-active': store.granularity === k }]"
        @click="onGranularity(k)"
      >{{ l }}</button>
    </div>

    <div class="filter-group">
      <span class="filter-label">店铺</span>
      <select class="select" :value="store.shopCode" @change="onShop($event.target.value)">
        <option v-for="s in shops" :key="s.code" :value="s.code">{{ s.code === 'all' ? '全部' : s.name }}</option>
      </select>
    </div>
    <div class="filter-group">
      <span class="filter-label">负责人</span>
      <select class="select" :value="store.owner" @change="onOwner($event.target.value)">
        <option v-for="o in owners" :key="o" :value="o">{{ ownerLabel(o) }}</option>
      </select>
    </div>
    <div class="filter-group">
      <span class="filter-label">类目</span>
      <select class="select" :value="store.category" @change="onCat($event.target.value)">
        <option v-for="c in cats" :key="c" :value="c">{{ catLabel(c) }}</option>
      </select>
    </div>

    <div class="spacer-x" />

    <div class="range-picker">
      <input
        type="date"
        class="date-input"
        :value="store.startDate"
        @change="onStart($event.target.value)"
        min="2024-01-01" max="2030-12-31"
      />
      <span class="range-sep">→</span>
      <input
        type="date"
        class="date-input"
        :value="store.endDate"
        @change="onEnd($event.target.value)"
        min="2024-01-01" max="2030-12-31"
      />
    </div>

    <div class="preset-row">
      <button class="chip sm" @click="preset(7)">近7天</button>
      <button class="chip sm" @click="preset(30)">近30天</button>
      <button class="chip sm" @click="preset(90)">近90天</button>
      <button class="chip sm" @click="presetThisMonth">本月</button>
      <button class="chip sm" @click="presetThisYear">本年</button>
    </div>

    <button class="btn" @click="emit('reset')">重置布局</button>
  </div>
</template>

<style scoped>
.range-picker {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface);
}
.range-picker .date-input { border: 0; padding: 6px 4px; background: transparent; }
.range-sep { color: var(--ink-5); font-size: 12px; }
.preset-row { display: inline-flex; gap: 4px; margin-left: 8px; }
.chip.sm { padding: 4px 10px; font-size: 12px; }
</style>
