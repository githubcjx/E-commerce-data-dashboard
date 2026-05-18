<script setup>
import { computed, ref } from "vue";
import { formatValue } from "../utils/format";

const props = defineProps({ rows: { type: Array, required: true } });
const sortKey = ref("sales");
const sortDir = ref("desc");

const sorted = computed(() => {
  const arr = (props.rows || []).slice();
  arr.sort((a, b) => {
    const va = a[sortKey.value];
    const vb = b[sortKey.value];
    if (typeof va === "string") {
      return sortDir.value === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    return sortDir.value === "asc" ? va - vb : vb - va;
  });
  return arr;
});

const maxSales = computed(() => Math.max(1, ...(props.rows || []).map((r) => r.sales)));

function sortBy(key) {
  if (sortKey.value === key) sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
  else { sortKey.value = key; sortDir.value = "desc"; }
}
function arrow(key) {
  if (sortKey.value !== key) return "";
  return sortDir.value === "asc" ? "↑" : "↓";
}
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">类目分类汇总</span>
      <span class="panel-subtitle">按销售额排序 · 共 {{ rows.length }} 项</span>
      <div class="panel-actions">
        <button class="btn ghost sm">导出 CSV</button>
        <slot name="handle" />
      </div>
    </header>
    <table class="tbl">
      <thead>
        <tr>
          <th style="cursor:pointer;text-align:left" @click="sortBy('name')">类目 <span style="margin-left:6px;color:var(--ink-5);font-family:var(--font-mono)">{{ arrow("name") }}</span></th>
          <th style="cursor:pointer" @click="sortBy('sales')">销售额 <span style="margin-left:6px;color:var(--ink-5);font-family:var(--font-mono)">{{ arrow("sales") }}</span></th>
          <th style="cursor:pointer" @click="sortBy('profit')">利润额 <span style="margin-left:6px;color:var(--ink-5);font-family:var(--font-mono)">{{ arrow("profit") }}</span></th>
          <th style="cursor:pointer" @click="sortBy('gross_margin')">毛利率 <span style="margin-left:6px;color:var(--ink-5);font-family:var(--font-mono)">{{ arrow("gross_margin") }}</span></th>
          <th style="cursor:pointer" @click="sortBy('refund_rate')">退款率 <span style="margin-left:6px;color:var(--ink-5);font-family:var(--font-mono)">{{ arrow("refund_rate") }}</span></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in sorted" :key="r.name">
          <td>{{ r.name }}</td>
          <td>
            {{ formatValue(r.sales, "currency") }}
            <span class="t-bar"><i :style="{ width: ((r.sales / maxSales) * 100) + '%' }" /></span>
          </td>
          <td :class="r.profit >= 0 ? 't-pos' : 't-neg'">{{ formatValue(r.profit, "currency") }}</td>
          <td>{{ formatValue(r.gross_margin, "percent") }}</td>
          <td :class="r.refund_rate >= 40 ? 't-neg' : ''">{{ formatValue(r.refund_rate, "percent") }}</td>
        </tr>
        <tr v-if="!sorted.length"><td colspan="5" class="empty-state">暂无数据，请先在「导入」页面上传 Excel</td></tr>
      </tbody>
    </table>
  </section>
</template>
