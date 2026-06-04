<script setup>
import { onMounted, ref, watch } from "vue";
import { fetchMyTargets } from "../api/targets";
import { useUiStore } from "../stores/ui";
import { formatCurrency } from "../utils/format";

const ui = useUiStore();

function currentYm() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const ym = ref(currentYm());
const loading = ref(false);
const rows = ref([]);

function pct(d) {
  return d === null || d === undefined ? "—" : (d * 100).toFixed(1) + "%";
}
function barWidth(d) {
  if (d === null || d === undefined) return "0%";
  return Math.max(0, Math.min(1, d)) * 100 + "%";
}
function barClass(d) {
  if (d === null || d === undefined) return "muted";
  if (d >= 1) return "ok";
  if (d >= 0.8) return "warn";
  return "low";
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchMyTargets(ym.value);
    rows.value = data.rows || [];
  } catch (e) {
    ui.showToast(e.message || "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(ym, load);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">我的目标达成</h1>
        <p class="page-sub">完成率 = 当月累计实际 ÷ 当月目标，随导入数据实时更新。</p>
      </div>
      <label class="month-pick">
        月份
        <input type="month" v-model="ym" />
      </label>
    </div>

    <div v-if="loading" class="empty">加载中…</div>
    <div v-else-if="!rows.length" class="empty">本月暂无可查看的目标数据。</div>
    <div v-else class="cards">
      <div v-for="r in rows" :key="r.owner" class="card">
        <div class="card-head">
          <span class="owner">{{ r.owner }}</span>
          <span v-if="!r.has_target" class="no-target">未设目标</span>
        </div>

        <div class="metric">
          <div class="metric-top">
            <span class="metric-label">销售额</span>
            <span :class="['metric-pct', barClass(r.sales_completion)]">{{ pct(r.sales_completion) }}</span>
          </div>
          <div class="bar"><span :class="['bar-fill', barClass(r.sales_completion)]" :style="{ width: barWidth(r.sales_completion) }" /></div>
          <div class="metric-sub mono">{{ formatCurrency(r.actual_sales) }} / {{ formatCurrency(r.target_sales) }}</div>
        </div>

        <div class="metric">
          <div class="metric-top">
            <span class="metric-label">利润额</span>
            <span :class="['metric-pct', barClass(r.profit_completion)]">{{ pct(r.profit_completion) }}</span>
          </div>
          <div class="bar"><span :class="['bar-fill', barClass(r.profit_completion)]" :style="{ width: barWidth(r.profit_completion) }" /></div>
          <div class="metric-sub mono">{{ formatCurrency(r.actual_profit) }} / {{ formatCurrency(r.target_profit) }}</div>
        </div>

        <div class="metric rate-row">
          <span class="metric-label">利润率</span>
          <span class="rate-vals">
            <b :class="r.target_profit_rate > 0 && r.actual_profit_rate >= r.target_profit_rate ? 'hit' : ''">{{ pct(r.actual_profit_rate) }}</b>
            <span class="rate-target">目标 {{ pct(r.target_profit_rate) }}</span>
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1100px; margin: 0 auto; padding: 20px 4px 60px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--ink); margin: 0; }
.page-sub { font-size: 13px; color: var(--ink-3); margin: 6px 0 0; }
.month-pick { font-size: 13px; color: var(--ink-3); display: inline-flex; align-items: center; gap: 8px; }
.month-pick input { font-family: inherit; font-size: 13px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--ink); }

.empty { padding: 48px; text-align: center; color: var(--ink-3); font-size: 13px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.owner { font-size: 15px; font-weight: 600; color: var(--ink); }
.no-target { font-size: 11px; color: var(--ink-3); background: var(--bg-elev); padding: 2px 8px; border-radius: 999px; }

.metric { margin-bottom: 14px; }
.metric-top { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 6px; }
.metric-label { font-size: 12.5px; color: var(--ink-3); }
.metric-pct { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.metric-pct.ok { color: #047857; }
.metric-pct.warn { color: #b45309; }
.metric-pct.low { color: #b91c1c; }
.metric-pct.muted { color: var(--ink-3); }
.bar { height: 7px; border-radius: 999px; background: var(--bg-elev); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 999px; transition: width 0.3s; }
.bar-fill.ok { background: #10b981; }
.bar-fill.warn { background: #f59e0b; }
.bar-fill.low { background: #ef4444; }
.bar-fill.muted { background: var(--border-strong); }
.metric-sub { margin-top: 5px; font-size: 11.5px; color: var(--ink-3); font-variant-numeric: tabular-nums; }

.rate-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0; padding-top: 4px; border-top: 1px dashed var(--divider); }
.rate-vals { display: inline-flex; align-items: baseline; gap: 8px; }
.rate-vals b { font-size: 14px; font-variant-numeric: tabular-nums; color: var(--ink); }
.rate-vals b.hit { color: #047857; }
.rate-target { font-size: 11.5px; color: var(--ink-3); }
</style>
