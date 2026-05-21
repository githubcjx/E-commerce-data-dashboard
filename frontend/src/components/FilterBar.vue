<script setup>
import { computed } from "vue";
import { useDashboardStore } from "../stores/dashboard";

const store = useDashboardStore();
const emit = defineEmits(["reset"]);

// Top filter: which period the user is looking at. Drives the date picker
// shape below + the default range when clicked.
const TOP_GRANS = [
  ["day",   "日"],
  ["week",  "周"],
  ["month", "月"],
  ["year",  "年"],
];

const shops = computed(() => [{ code: "all", name: "全部" }, ...(store.filters.shops || [])]);
const owners = computed(() => ["all", ...(store.filters.owners || [])]);
const cats = computed(() => ["all", ...(store.filters.categories || [])]);

function ownerLabel(v) { return v === "all" ? "全部" : v; }
function catLabel(v) { return v === "all" ? "全部" : v; }

async function onTab(g) {
  if (store.topGranularity === g) return;
  await store.setTopGranularity(g);
}

async function onShop(v) { store.shopCode = v; await store.loadAll(); }
async function onOwner(v) { store.owner = v; await store.loadAll(); }
async function onCat(v) { store.category = v; await store.loadAll(); }

// ---------------------------------------------------------------------------
// Date helpers (local time, ISO output)
// ---------------------------------------------------------------------------
function toIso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function parseIso(s) {
  if (!s) return null;
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

// ISO week (ISO 8601: weeks start Monday, week 1 contains Jan 4)
function getIsoWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  const weekNum = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
  return { year: d.getUTCFullYear(), week: weekNum };
}
function dateToWeekStr(date) {
  const { year, week } = getIsoWeek(date);
  return `${year}-W${String(week).padStart(2, "0")}`;
}
function weekStrToRange(weekStr) {
  const m = /^(\d{4})-W(\d{2})$/.exec(weekStr);
  if (!m) return null;
  const y = Number(m[1]), w = Number(m[2]);
  // Find Monday of week 1 (the week containing Jan 4).
  const jan4 = new Date(y, 0, 4);
  const jan4Day = (jan4.getDay() + 6) % 7;
  const w1Mon = new Date(jan4);
  w1Mon.setDate(jan4.getDate() - jan4Day);
  const start = new Date(w1Mon);
  start.setDate(w1Mon.getDate() + (w - 1) * 7);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return [start, end];
}

function dateToMonthStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function monthStrToBounds(monthStr) {
  const [y, m] = monthStr.split("-").map(Number);
  return [new Date(y, m - 1, 1), new Date(y, m, 0)]; // last day of month
}

// ---------------------------------------------------------------------------
// Bound the input values back to display from store.startDate / endDate
// ---------------------------------------------------------------------------
const weekStartValue  = computed(() => dateToWeekStr(parseIso(store.startDate) || new Date()));
const weekEndValue    = computed(() => dateToWeekStr(parseIso(store.endDate)   || new Date()));
const monthStartValue = computed(() => dateToMonthStr(parseIso(store.startDate) || new Date()));
const monthEndValue   = computed(() => dateToMonthStr(parseIso(store.endDate)   || new Date()));
const yearStartValue  = computed(() => (parseIso(store.startDate) || new Date()).getFullYear());
const yearEndValue    = computed(() => (parseIso(store.endDate)   || new Date()).getFullYear());

// ---------------------------------------------------------------------------
// Picker change handlers — keep store start ≤ end and reload.
// ---------------------------------------------------------------------------
async function onDayStart(v) {
  if (!v) return;
  const end = v > store.endDate ? v : store.endDate;
  await store.setRange(v, end);
}
async function onDayEnd(v) {
  if (!v) return;
  const start = v < store.startDate ? v : store.startDate;
  await store.setRange(start, v);
}
async function onWeekStart(v) {
  const r = weekStrToRange(v);
  if (!r) return;
  const startIso = toIso(r[0]);
  // If new start is past the current end, pull the end to this week's end too.
  const endStr = startIso > store.endDate ? toIso(r[1]) : store.endDate;
  await store.setRange(startIso, endStr);
}
async function onWeekEnd(v) {
  const r = weekStrToRange(v);
  if (!r) return;
  const endIso = toIso(r[1]);
  const startStr = endIso < store.startDate ? toIso(r[0]) : store.startDate;
  await store.setRange(startStr, endIso);
}
async function onMonthStart(v) {
  if (!v) return;
  const [s] = monthStrToBounds(v);
  const startIso = toIso(s);
  // If startMonth would exceed endMonth, snap endMonth to startMonth's end.
  const endStr = startIso > store.endDate ? toIso(monthStrToBounds(v)[1]) : store.endDate;
  await store.setRange(startIso, endStr);
}
async function onMonthEnd(v) {
  if (!v) return;
  const [, e] = monthStrToBounds(v);
  const endIso = toIso(e);
  const startStr = endIso < store.startDate
    ? toIso(monthStrToBounds(v)[0])
    : store.startDate;
  await store.setRange(startStr, endIso);
}
async function onYearStart(v) {
  const y = Number(v);
  if (!Number.isFinite(y) || y < 2000 || y > 2100) return;
  const startIso = toIso(new Date(y, 0, 1));
  const endStr = startIso > store.endDate ? toIso(new Date(y, 11, 31)) : store.endDate;
  await store.setRange(startIso, endStr);
}
async function onYearEnd(v) {
  const y = Number(v);
  if (!Number.isFinite(y) || y < 2000 || y > 2100) return;
  const endIso = toIso(new Date(y, 11, 31));
  const startStr = endIso < store.startDate ? toIso(new Date(y, 0, 1)) : store.startDate;
  await store.setRange(startStr, endIso);
}
</script>

<template>
  <div class="filter-row">
    <!-- Top granularity tabs: 日 / 周 / 月 / 年 -->
    <div class="seg" role="tablist">
      <button
        v-for="[k, l] in TOP_GRANS" :key="k"
        :class="['seg-btn', { 'is-active': store.topGranularity === k }]"
        @click="onTab(k)"
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

    <!-- Context-aware date picker -->
    <div class="range-picker">
      <!-- 日: start + end date -->
      <template v-if="store.topGranularity === 'day'">
        <input type="date" class="date-input"
          :value="store.startDate" @change="onDayStart($event.target.value)"
          min="2024-01-01" max="2030-12-31" />
        <span class="range-sep">→</span>
        <input type="date" class="date-input"
          :value="store.endDate" @change="onDayEnd($event.target.value)"
          min="2024-01-01" max="2030-12-31" />
      </template>

      <!-- 周: start + end week (range) -->
      <template v-else-if="store.topGranularity === 'week'">
        <input type="week" class="date-input week-input"
          :value="weekStartValue" @change="onWeekStart($event.target.value)" />
        <span class="range-sep">→</span>
        <input type="week" class="date-input week-input"
          :value="weekEndValue" @change="onWeekEnd($event.target.value)" />
      </template>

      <!-- 月: start + end month -->
      <template v-else-if="store.topGranularity === 'month'">
        <input type="month" class="date-input"
          :value="monthStartValue" @change="onMonthStart($event.target.value)" />
        <span class="range-sep">→</span>
        <input type="month" class="date-input"
          :value="monthEndValue" @change="onMonthEnd($event.target.value)" />
      </template>

      <!-- 年: start + end year -->
      <template v-else>
        <input type="number" class="date-input year-input"
          :value="yearStartValue" @change="onYearStart($event.target.value)"
          min="2000" max="2100" step="1" />
        <span class="range-sep">→</span>
        <input type="number" class="date-input year-input"
          :value="yearEndValue" @change="onYearEnd($event.target.value)"
          min="2000" max="2100" step="1" />
      </template>
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
.range-picker .date-input { border: 0; padding: 6px 4px; background: transparent; font-family: var(--font-mono); font-size: 13px; }
.range-picker .week-input { width: 130px; }
.range-picker .year-input { width: 64px; text-align: center; }
.range-sep { color: var(--ink-5); font-size: 12px; }
</style>
