<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from "vue";
import { useDashboardStore } from "../stores/dashboard";
import { useUserStore } from "../stores/user";

const store = useDashboardStore();
const userStore = useUserStore();
const emit = defineEmits(["reset"]);

// Visible to any tenant admin tier (super or plain admin) — they all
// need to switch which department's 部门视角 limits the dashboard. Plain
// 普通用户 don't get this picker.
const showDeptViewPicker = computed(
  () => userStore.isTenantSuperAdmin || userStore.isTenantPlainAdmin,
);
async function onViewDept(v) {
  await store.setViewDepartmentId(v === "" ? null : v);
}

// ---------------------------------------------------------------------------
// Multi-select pickers (负责人 / 店铺 / 类目)
// ---------------------------------------------------------------------------
// Build option lists. Shops use {code, name}; owners + categories are flat
// strings. Empty store selection = 全部 (the filter is off).
// Shop options restricted by 部门视角 — when a department is selected the
// dropdown only lists that department's view-shops. availableShops is the
// store getter that does this filtering.
const shopOptions = computed(() =>
  (store.availableShops || []).map((s) => ({ value: s.code, label: s.name || s.code }))
);
const ownerOptions = computed(() =>
  (store.filters.owners || []).map((n) => ({ value: n, label: n }))
);
const categoryOptions = computed(() =>
  (store.filters.categories || []).map((c) => ({ value: c, label: c }))
);

// Label shown on the closed pill. "全部" when nothing selected, the single
// label when one is selected, "{first} +N" otherwise.
function pillLabel(selected, options) {
  if (!selected.length) return "全部";
  const lookup = new Map(options.map((o) => [o.value, o.label]));
  const labels = selected.map((v) => lookup.get(v) || v);
  if (labels.length === 1) return labels[0];
  return `${labels[0]} +${labels.length - 1}`;
}

// Open-state tracking — only one popover open at a time.
const openId = ref(null);
function toggleOpen(id) { openId.value = openId.value === id ? null : id; }
function closeAll() { openId.value = null; }

// Close on outside click.
function onDocClick(e) {
  if (!e.target.closest(".ms-wrap")) closeAll();
}
onMounted(() => document.addEventListener("click", onDocClick));
onBeforeUnmount(() => document.removeEventListener("click", onDocClick));

// Generic toggle for a value in one of the selected arrays.
function toggleValue(arr, value) {
  const i = arr.indexOf(value);
  if (i === -1) arr.push(value); else arr.splice(i, 1);
}

async function onOwnerToggle(value) {
  toggleValue(store.owners, value);
  await store.loadAll();
}
async function onShopToggle(value) {
  toggleValue(store.shopCodes, value);
  await store.loadAll();
}
async function onCategoryToggle(value) {
  toggleValue(store.categories, value);
  await store.loadAll();
}
async function onSelectAll(which) {
  // "全部" = empty array (no filter). Snappier than checking every box.
  store[which] = [];
  await store.loadAll();
}

// Top filter: which period the user is looking at. Drives the date picker
// shape below + the default range when clicked.
const TOP_GRANS = [
  ["day",   "日"],
  ["week",  "周"],
  ["month", "月"],
  ["year",  "年"],
];

async function onTab(g) {
  if (store.topGranularity === g) return;
  await store.setTopGranularity(g);
}

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

    <!-- Order: 部门视角 → 负责人 → 店铺 → 类目. 部门视角 limits which
         shops appear in the 店铺 dropdown (their view_shops only). -->
    <div v-if="showDeptViewPicker" class="filter-group">
      <span class="filter-label" title="选择部门视角后，看板只展示该部门下的店铺数据">部门视角</span>
      <select
        class="select"
        :value="store.viewDepartmentId == null ? '' : store.viewDepartmentId"
        @change="onViewDept($event.target.value)"
      >
        <option value="">不指定</option>
        <option
          v-for="d in store.departmentOptions" :key="d.id" :value="d.id"
        >{{ d.name }}</option>
      </select>
    </div>

    <div class="filter-group ms-wrap">
      <span class="filter-label">负责人</span>
      <button
        type="button"
        :class="['select ms-trigger', { 'has-selection': store.owners.length }]"
        @click.stop="toggleOpen('owner')"
      >
        <span>{{ pillLabel(store.owners, ownerOptions) }}</span>
        <span class="ms-chev">▾</span>
      </button>
      <div v-if="openId === 'owner'" class="ms-pop" @click.stop>
        <button type="button" class="ms-item all-row" @click="onSelectAll('owners')">
          <span class="ms-check" :class="{ on: !store.owners.length }">✓</span>
          全部
        </button>
        <div class="ms-divider" />
        <button
          v-for="o in ownerOptions" :key="o.value"
          type="button" class="ms-item"
          @click="onOwnerToggle(o.value)"
        >
          <span class="ms-check" :class="{ on: store.owners.includes(o.value) }">✓</span>
          {{ o.label }}
        </button>
        <div v-if="!ownerOptions.length" class="ms-empty">暂无可选项</div>
      </div>
    </div>

    <div class="filter-group ms-wrap">
      <span class="filter-label">店铺</span>
      <button
        type="button"
        :class="['select ms-trigger', { 'has-selection': store.shopCodes.length }]"
        @click.stop="toggleOpen('shop')"
      >
        <span>{{ pillLabel(store.shopCodes, shopOptions) }}</span>
        <span class="ms-chev">▾</span>
      </button>
      <div v-if="openId === 'shop'" class="ms-pop" @click.stop>
        <button type="button" class="ms-item all-row" @click="onSelectAll('shopCodes')">
          <span class="ms-check" :class="{ on: !store.shopCodes.length }">✓</span>
          全部
        </button>
        <div class="ms-divider" />
        <button
          v-for="s in shopOptions" :key="s.value"
          type="button" class="ms-item"
          @click="onShopToggle(s.value)"
        >
          <span class="ms-check" :class="{ on: store.shopCodes.includes(s.value) }">✓</span>
          {{ s.label }}
        </button>
        <div v-if="!shopOptions.length" class="ms-empty">暂无可选项</div>
      </div>
    </div>

    <div class="filter-group ms-wrap">
      <span class="filter-label">类目</span>
      <button
        type="button"
        :class="['select ms-trigger', { 'has-selection': store.categories.length }]"
        @click.stop="toggleOpen('cat')"
      >
        <span>{{ pillLabel(store.categories, categoryOptions) }}</span>
        <span class="ms-chev">▾</span>
      </button>
      <div v-if="openId === 'cat'" class="ms-pop" @click.stop>
        <button type="button" class="ms-item all-row" @click="onSelectAll('categories')">
          <span class="ms-check" :class="{ on: !store.categories.length }">✓</span>
          全部
        </button>
        <div class="ms-divider" />
        <button
          v-for="c in categoryOptions" :key="c.value"
          type="button" class="ms-item"
          @click="onCategoryToggle(c.value)"
        >
          <span class="ms-check" :class="{ on: store.categories.includes(c.value) }">✓</span>
          {{ c.label }}
        </button>
        <div v-if="!categoryOptions.length" class="ms-empty">暂无可选项</div>
      </div>
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

/* Multi-select picker — looks like the native select on the closed state,
   opens a chip checkbox list on click. Closes on outside click or via the
   trigger toggle. Selection-on-pill: "全部" when empty, "A" when one,
   "A +N" when many. */
.ms-wrap { position: relative; }
.ms-trigger {
  display: inline-flex; align-items: center; justify-content: space-between;
  gap: 6px; cursor: pointer; min-width: 110px; max-width: 220px;
  text-align: left;
}
.ms-trigger > span:first-child {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ms-trigger.has-selection {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-ink);
}
.ms-chev { font-size: 10px; color: var(--ink-4); flex-shrink: 0; }
.ms-pop {
  position: absolute; left: 0; top: calc(100% + 4px); z-index: 50;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; box-shadow: var(--shadow-pop);
  min-width: 180px; max-width: 280px; max-height: 280px;
  overflow-y: auto; padding: 4px;
}
.ms-item {
  display: flex; align-items: center; gap: 8px;
  width: 100%; padding: 7px 10px; border-radius: 6px;
  appearance: none; border: 0; background: transparent;
  font: inherit; font-size: 13px; color: var(--ink);
  text-align: left; cursor: pointer;
}
.ms-item:hover { background: var(--surface-hover); }
.ms-item.all-row { font-weight: 500; }
.ms-check {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border: 1px solid var(--border);
  border-radius: 4px; font-size: 11px; color: transparent;
  background: var(--surface); flex-shrink: 0;
  transition: background .15s, border-color .15s, color .15s;
}
.ms-check.on {
  background: var(--accent); border-color: var(--accent);
  color: #fff;
}
.ms-divider { height: 1px; background: var(--divider); margin: 4px 2px; }
.ms-empty {
  padding: 12px 10px; font-size: 12px; color: var(--ink-4); text-align: center;
}
</style>
