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
function statusClass(d) {
  if (d === null || d === undefined) return "muted";
  if (d >= 1) return "ok";
  if (d >= 0.8) return "warn";
  return "low";
}
const achieved = (c) => c !== null && c !== undefined && c >= 1;
const marginHit = (r) => r.target_profit_rate > 0 && r.actual_profit_rate >= r.target_profit_rate;

// Count, per owner, how many of the (set) targets are achieved — drives the
// header chip and the "all done" celebratory accent.
function summarize(r) {
  let set = 0, hit = 0;
  if (r.target_sales > 0) { set++; if (achieved(r.sales_completion)) hit++; }
  if (r.target_profit > 0) { set++; if (achieved(r.profit_completion)) hit++; }
  if (r.target_profit_rate > 0) { set++; if (marginHit(r)) hit++; }
  return { set, hit, complete: set > 0 && hit === set };
}

async function load() {
  loading.value = true;
  try {
    const data = await fetchMyTargets(ym.value);
    rows.value = (data.rows || []).map((r) => ({ ...r, _sum: summarize(r) }));
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
      <div v-for="r in rows" :key="r.owner" :class="['card', { 'card--complete': r._sum.complete }]">
        <!-- header: 负责人 + 达成进度 -->
        <div class="card-head">
          <span class="owner">{{ r.owner }}</span>
          <span v-if="r._sum.set" :class="['summary', { all: r._sum.complete }]">
            <svg v-if="r._sum.complete" class="summary-check" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
            达成 {{ r._sum.hit }}/{{ r._sum.set }}
          </span>
          <span v-else class="no-target">未设目标</span>
        </div>

        <!-- 销售额 -->
        <div class="metric">
          <div class="metric-top">
            <span class="metric-label">销售额完成率</span>
            <span v-if="achieved(r.sales_completion)" class="check" title="已达成">
              <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
            </span>
          </div>
          <div :class="['hero', statusClass(r.sales_completion)]">{{ pct(r.sales_completion) }}</div>
          <div class="bar"><span :class="['bar-fill', statusClass(r.sales_completion)]" :style="{ width: barWidth(r.sales_completion) }" /></div>
          <div class="metric-sub">
            <span>实际 <b class="mono">{{ formatCurrency(r.actual_sales) }}</b></span>
            <span class="tgt">目标 <span class="mono">{{ formatCurrency(r.target_sales) }}</span></span>
          </div>
        </div>

        <!-- 利润额 -->
        <div class="metric">
          <div class="metric-top">
            <span class="metric-label">利润额完成率</span>
            <span v-if="achieved(r.profit_completion)" class="check" title="已达成">
              <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
            </span>
          </div>
          <div :class="['hero', statusClass(r.profit_completion)]">{{ pct(r.profit_completion) }}</div>
          <div class="bar"><span :class="['bar-fill', statusClass(r.profit_completion)]" :style="{ width: barWidth(r.profit_completion) }" /></div>
          <div class="metric-sub">
            <span>实际 <b class="mono">{{ formatCurrency(r.actual_profit) }}</b></span>
            <span class="tgt">目标 <span class="mono">{{ formatCurrency(r.target_profit) }}</span></span>
          </div>
        </div>

        <!-- 利润率 (实际 vs 目标，无完成率排名) -->
        <div class="metric rate-metric">
          <div class="metric-top">
            <span class="metric-label">利润率</span>
            <span v-if="marginHit(r)" class="check" title="已达标">
              <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
            </span>
          </div>
          <div class="rate-row">
            <span :class="['rate-actual', { hit: marginHit(r) }]">{{ pct(r.actual_profit_rate) }}</span>
            <span class="rate-target">目标 {{ pct(r.target_profit_rate) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1280px; margin: 0 auto; padding: 24px 8px 72px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 22px; }
.page-title { font-size: 24px; font-weight: 700; color: var(--ink); margin: 0; letter-spacing: -0.01em; }
.page-sub { font-size: 13.5px; color: var(--ink-3); margin: 8px 0 0; }
.month-pick { font-size: 13px; color: var(--ink-3); display: inline-flex; align-items: center; gap: 8px; }
.month-pick input { font-family: inherit; font-size: 14px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); color: var(--ink); }

.empty { padding: 64px; text-align: center; color: var(--ink-3); font-size: 14px; }

/* roomier grid + cards */
/* auto-fit (not auto-fill): with 1–2 cards they STRETCH to fill the row instead
   of leaving empty tracks; the page's 1280px max-width caps the grid at 3
   columns, and it drops to 2 / 1 columns responsively as the viewport narrows. */
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 22px; }
.card {
  position: relative; background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px 24px 22px; overflow: hidden;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.card:hover { box-shadow: var(--shadow-pop); }
/* all targets met → green accent */
.card--complete { border-color: rgba(16, 185, 129, 0.5); }
.card--complete::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px;
  background: linear-gradient(180deg, #10b981, #059669);
}

.card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
.owner { font-size: 18px; font-weight: 700; color: var(--ink); }
.summary {
  margin-left: auto; display: inline-flex; align-items: center; gap: 5px;
  font-size: 12.5px; font-weight: 600; color: var(--ink-3);
  background: var(--bg-elev); padding: 4px 11px; border-radius: 999px;
}
.summary.all { color: #047857; background: rgba(16, 185, 129, 0.14); }
.summary-check { width: 14px; height: 14px; stroke: #059669; stroke-width: 3.2; fill: none; stroke-linecap: round; stroke-linejoin: round; }
.no-target { margin-left: auto; font-size: 12px; color: var(--ink-3); background: var(--bg-elev); padding: 4px 11px; border-radius: 999px; }

.metric { padding: 16px 0; border-top: 1px solid var(--divider); }
.metric:first-of-type { border-top: 0; padding-top: 0; }
.metric-top { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.metric-label { font-size: 13.5px; font-weight: 500; color: var(--ink-2); }

/* the hero number — big + colored, the thing you see first */
.hero { font-size: 40px; line-height: 1.05; font-weight: 800; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; margin: 2px 0 12px; }
.hero.ok { color: #059669; }
.hero.warn { color: #d97706; }
.hero.low { color: #dc2626; }
.hero.muted { color: var(--ink-3); }

.bar { height: 10px; border-radius: 999px; background: var(--bg-elev); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: 999px; transition: width 0.45s ease; }
.bar-fill.ok { background: linear-gradient(90deg, #10b981, #059669); }
.bar-fill.warn { background: linear-gradient(90deg, #fbbf24, #d97706); }
.bar-fill.low { background: linear-gradient(90deg, #f87171, #dc2626); }
.bar-fill.muted { background: var(--border-strong); }

.metric-sub { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-top: 10px; font-size: 13.5px; color: var(--ink-2); }
.metric-sub b { font-weight: 700; color: var(--ink); font-size: 14.5px; }
.metric-sub .tgt { color: var(--ink-3); font-size: 12.5px; }
.metric-sub .mono { font-variant-numeric: tabular-nums; }

/* green check badge */
.check { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 999px; background: #10b981; flex: none; box-shadow: 0 1px 4px rgba(16, 185, 129, 0.4); }
.check svg { width: 16px; height: 16px; stroke: #fff; stroke-width: 3.2; fill: none; stroke-linecap: round; stroke-linejoin: round; }

/* 利润率 block */
.rate-metric { padding-bottom: 2px; }
.rate-row { display: flex; align-items: baseline; gap: 12px; margin-top: 4px; }
.rate-actual { font-size: 30px; font-weight: 800; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; color: var(--ink); }
.rate-actual.hit { color: #059669; }
.rate-target { font-size: 13.5px; color: var(--ink-3); }

@media (max-width: 540px) {
  .cards { grid-template-columns: 1fr; }
  .hero { font-size: 36px; }
}
</style>
