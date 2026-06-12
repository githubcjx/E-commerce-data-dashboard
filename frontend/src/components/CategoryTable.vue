<script setup>
import { computed, ref } from "vue";
import { formatValue } from "../utils/format";
import { useDashboardStore } from "../stores/dashboard";

const props = defineProps({ rows: { type: Array, required: true } });
const store = useDashboardStore();
const sortKey = ref("sales");
const sortDir = ref("desc");

// 环比对比的具体日期范围 — e.g. "2025-05-01 ~ 2025-05-07"
const prevLabel = computed(() => store.previousLabel || "上期");

const sorted = computed(() => {
  const arr = (props.rows || []).slice();
  arr.sort((a, b) => {
    const va = a[sortKey.value];
    const vb = b[sortKey.value];
    if (typeof va === "string") {
      return sortDir.value === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
    }
    return sortDir.value === "asc" ? (va ?? 0) - (vb ?? 0) : (vb ?? 0) - (va ?? 0);
  });
  return arr;
});

const maxSales = computed(() => Math.max(1, ...(props.rows || []).map((r) => r.sales || 0)));

function sortBy(key) {
  if (sortKey.value === key) sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
  else { sortKey.value = key; sortDir.value = "desc"; }
}
function arrow(key) {
  if (sortKey.value !== key) return "";
  return sortDir.value === "asc" ? "↑" : "↓";
}

// 环比 cell — show "+12.34%" / "−5.67%" / "—"
function delta(v) {
  if (v === null || v === undefined) return { text: "—", cls: "t-muted" };
  const sign = v >= 0 ? "+" : "−";
  const cls = v > 0 ? "t-pos" : v < 0 ? "t-neg" : "t-muted";
  return { text: `${sign}${Math.abs(v).toFixed(2)}%`, cls };
}

// 差额 cell — 百分点差（本期率 − 上期率，如 8% vs 7% → +1.00%），不是环比变化率
const rateDiff = delta;

function prevRateTitle(v) {
  if (v === null || v === undefined) return "上期无数据";
  return `上期 ${Number(v).toFixed(2)}%`;
}
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">类目分类汇总</span>
      <span class="panel-subtitle">按销售额排序 · 共 {{ rows.length }} 项</span>
      <div class="panel-actions">
        <slot name="handle" />
      </div>
    </header>
    <div class="cat-scroll">
    <table class="tbl cat-tbl">
      <thead>
        <tr>
          <th style="cursor:pointer;text-align:left" @click="sortBy('name')">
            类目 <span class="sort-mark">{{ arrow("name") }}</span>
          </th>
          <th style="cursor:pointer" @click="sortBy('sales')">
            销售额 <span class="sort-mark">{{ arrow("sales") }}</span>
          </th>
          <th>
            <div>销售额环比</div>
            <div class="prev-sub">对比 {{ prevLabel }}</div>
          </th>
          <th style="cursor:pointer" @click="sortBy('profit')">
            利润额 <span class="sort-mark">{{ arrow("profit") }}</span>
          </th>
          <th>
            <div>利润额环比</div>
            <div class="prev-sub">对比 {{ prevLabel }}</div>
          </th>
          <th style="cursor:pointer" @click="sortBy('company_profit_rate')">
            公司利润率 <span class="sort-mark">{{ arrow("company_profit_rate") }}</span>
          </th>
          <th>
            <div>利润率差额</div>
            <div class="prev-sub">对比 {{ prevLabel }}</div>
          </th>
          <th style="cursor:pointer" @click="sortBy('cost_rate')">
            成本率 <span class="sort-mark">{{ arrow("cost_rate") }}</span>
          </th>
          <th>
            <div>成本率差额</div>
            <div class="prev-sub">对比 {{ prevLabel }}</div>
          </th>
          <th style="cursor:pointer" @click="sortBy('refund_rate')">
            发货退款率 <span class="sort-mark">{{ arrow("refund_rate") }}</span>
          </th>
          <th style="cursor:pointer" @click="sortBy('ship_pct')">
            快递费率 <span class="sort-mark">{{ arrow("ship_pct") }}</span>
          </th>
          <th>
            <div>快递费率差额</div>
            <div class="prev-sub">对比 {{ prevLabel }}</div>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in sorted" :key="r.name">
          <td>{{ r.name }}</td>
          <td>
            {{ formatValue(r.sales, "currency") }}
            <span class="t-bar"><i :style="{ width: ((r.sales / maxSales) * 100) + '%' }" /></span>
          </td>
          <td :class="delta(r.sales_delta_pct).cls" :title="`对比上期 ${formatValue(r.sales_prev || 0, 'currency')}`">
            {{ delta(r.sales_delta_pct).text }}
          </td>
          <td :class="r.profit >= 0 ? 't-pos' : 't-neg'">{{ formatValue(r.profit, "currency") }}</td>
          <td :class="delta(r.profit_delta_pct).cls" :title="`对比上期 ${formatValue(r.profit_prev || 0, 'currency')}`">
            {{ delta(r.profit_delta_pct).text }}
          </td>
          <td :class="r.company_profit_rate < 0 ? 't-neg' : ''">{{ formatValue(r.company_profit_rate, "percent") }}</td>
          <td :class="rateDiff(r.company_profit_rate_diff).cls" :title="prevRateTitle(r.company_profit_rate_prev)">
            {{ rateDiff(r.company_profit_rate_diff).text }}
          </td>
          <td>{{ formatValue(r.cost_rate, "percent") }}</td>
          <td :class="rateDiff(r.cost_rate_diff).cls" :title="prevRateTitle(r.cost_rate_prev)">
            {{ rateDiff(r.cost_rate_diff).text }}
          </td>
          <td :class="r.refund_rate >= 40 ? 't-neg' : ''">{{ formatValue(r.refund_rate, "percent") }}</td>
          <td>{{ formatValue(r.ship_pct, "percent") }}</td>
          <td :class="rateDiff(r.ship_pct_diff).cls" :title="prevRateTitle(r.ship_pct_prev)">
            {{ rateDiff(r.ship_pct_diff).text }}
          </td>
        </tr>
        <tr v-if="!sorted.length"><td colspan="12" class="empty-state">暂无数据，请先在「导入」页面上传 Excel</td></tr>
      </tbody>
    </table>
    </div>
  </section>
</template>

<style scoped>
/* 12 列 nowrap 在窄屏可能超出面板宽度 — 兜底横向滚动而不是截断表头 */
.cat-scroll { overflow-x: auto; }
.cat-tbl th, .cat-tbl td { white-space: nowrap; }
.sort-mark { margin-left: 6px; color: var(--ink-5); font-family: var(--font-mono); }
.prev-sub {
  font-size: 11px; font-weight: 400; color: var(--ink-5);
  font-family: var(--font-mono); margin-top: 2px;
}
</style>
