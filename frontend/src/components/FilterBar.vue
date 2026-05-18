<script setup>
import { computed } from "vue";
import { useDashboardStore } from "../stores/dashboard";

const store = useDashboardStore();
const emit = defineEmits(["reset"]);

const granularities = [
  ["day", "日"],
  ["week", "周"],
  ["month", "月"],
];

const shops = computed(() => [{ code: "all", name: "全部" }, ...(store.filters.shops || [])]);
const owners = computed(() => ["all", ...(store.filters.owners || [])]);
const cats = computed(() => ["all", ...(store.filters.categories || [])]);

function ownerLabel(v) { return v === "all" ? "全部" : v; }
function catLabel(v) { return v === "all" ? "全部" : v; }

async function refresh() {
  await store.loadAll();
}

async function onGranularity(k) { store.granularity = k; await refresh(); }
async function onShop(v) { store.shopCode = v; await refresh(); }
async function onOwner(v) { store.owner = v; await refresh(); }
async function onCat(v) { store.category = v; await refresh(); }
async function onDate(v) { store.endDate = v; await refresh(); }
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

    <input
      type="date"
      class="date-input"
      :value="store.endDate"
      @change="onDate($event.target.value)"
      min="2024-01-01"
      max="2030-12-31"
    />
    <button class="btn" @click="emit('reset')">重置布局</button>
  </div>
</template>
