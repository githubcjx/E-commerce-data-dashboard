<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { listTargets, saveTargets, fetchRanking } from "../api/targets";
import { useUserStore } from "../stores/user";
import { useUiStore } from "../stores/ui";
import { formatCurrency } from "../utils/format";

const userStore = useUserStore();
const ui = useUiStore();
const route = useRoute();

// Only super_admin (or platform acting in-tenant) may edit; plain admin views.
const canEdit = computed(() => userStore.canEditTargets);

function currentYm() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const validYm = (v) => typeof v === "string" && /^\d{4}-\d{2}$/.test(v);
const ym = ref(validYm(route.query.ym) ? route.query.ym : currentYm());

const activeTab = ref("edit"); // edit | rank
const loading = ref(false);
const saving = ref(false);
const rows = ref([]); // editable grid rows (+ _rate_pct for the % input)
const ranking = ref({ sales_ranking: [], profit_ranking: [] });

// decimal → "87.5%"
function pct(d) {
  return d === null || d === undefined ? "—" : (d * 100).toFixed(1) + "%";
}
function compClass(d) {
  if (d === null || d === undefined) return "muted";
  if (d >= 1) return "ok";
  if (d >= 0.8) return "warn";
  return "low";
}
const achieved = (c) => c !== null && c !== undefined && c >= 1;
const marginHit = (r) => r.target_profit_rate > 0 && r.actual_profit_rate >= r.target_profit_rate;

async function loadGrid() {
  loading.value = true;
  try {
    const data = await listTargets(ym.value);
    rows.value = (data.rows || []).map((r) => ({
      ...r,
      _rate_pct: +(Number(r.target_profit_rate) * 100).toFixed(2),
    }));
  } catch (e) {
    ui.showToast(e.message || "加载失败", "error");
  } finally {
    loading.value = false;
  }
}

async function loadRanking() {
  try {
    ranking.value = await fetchRanking(ym.value);
  } catch (e) {
    ui.showToast(e.message || "加载失败", "error");
  }
}

async function reload() {
  await Promise.all([loadGrid(), loadRanking()]);
}

async function save() {
  if (!canEdit.value) return;
  saving.value = true;
  try {
    const items = rows.value.map((r) => ({
      owner: r.owner,
      target_sales: Number(r.target_sales) || 0,
      target_profit: Number(r.target_profit) || 0,
      target_profit_rate: (Number(r._rate_pct) || 0) / 100,
    }));
    await saveTargets(ym.value, items);
    ui.showToast(`已保存 ${items.length} 人`, "success");
    await reload();
  } catch (e) {
    ui.showToast(e.message || "保存失败", "error");
  } finally {
    saving.value = false;
  }
}

onMounted(reload);
watch(ym, reload);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">人员目标完成情况</h1>
        <p class="page-sub">
          按月设置每位负责人的业绩目标，完成率由系统按当月实际数据自动计算（经营口径）。
        </p>
      </div>
      <div class="head-controls">
        <label class="month-pick">
          月份
          <input type="month" v-model="ym" />
        </label>
      </div>
    </div>

    <div class="tabs-row">
      <button :class="['seg', { on: activeTab === 'edit' }]" @click="activeTab = 'edit'">目标设置</button>
      <button :class="['seg', { on: activeTab === 'rank' }]" @click="activeTab = 'rank'">完成排名</button>
      <div class="spacer" />
      <button
        v-if="activeTab === 'edit' && canEdit"
        class="btn primary"
        :disabled="saving || loading || !rows.length"
        @click="save"
      >{{ saving ? "保存中…" : "保存目标" }}</button>
    </div>

    <!-- 目标设置 -->
    <section v-show="activeTab === 'edit'" class="card">
      <div v-if="!canEdit" class="readonly-hint">当前角色仅可查看，编辑目标需超级管理员。</div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="!rows.length" class="empty">暂无负责人数据（需先导入销售数据）。</div>
      <div v-else class="table-wrap">
        <table class="grid">
          <thead>
            <tr>
              <th class="sticky-l">负责人</th>
              <th>目标销售额</th>
              <th>实际销售额</th>
              <th>完成率</th>
              <th>目标利润额</th>
              <th>实际利润额</th>
              <th>完成率</th>
              <th>目标利润率</th>
              <th>实际利润率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.owner">
              <td class="sticky-l owner">{{ r.owner }}</td>
              <td>
                <input class="num" type="number" min="0" step="0.01"
                       v-model.number="r.target_sales" :disabled="!canEdit" />
              </td>
              <td class="ro">{{ formatCurrency(r.actual_sales) }}</td>
              <td>
                <span class="comp">
                  <span :class="['pill', compClass(r.sales_completion)]">{{ pct(r.sales_completion) }}</span>
                  <span v-if="achieved(r.sales_completion)" class="check" title="已达成"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
                </span>
              </td>
              <td>
                <input class="num" type="number" step="0.01"
                       v-model.number="r.target_profit" :disabled="!canEdit" />
              </td>
              <td class="ro">{{ formatCurrency(r.actual_profit) }}</td>
              <td>
                <span class="comp">
                  <span :class="['pill', compClass(r.profit_completion)]">{{ pct(r.profit_completion) }}</span>
                  <span v-if="achieved(r.profit_completion)" class="check" title="已达成"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
                </span>
              </td>
              <td>
                <div class="rate-input">
                  <input class="num" type="number" step="0.1"
                         v-model.number="r._rate_pct" :disabled="!canEdit" />
                  <span class="suffix">%</span>
                </div>
              </td>
              <td class="ro">
                <span class="comp">
                  {{ pct(r.actual_profit_rate) }}
                  <span v-if="marginHit(r)" class="check" title="已达标"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 完成排名 -->
    <section v-show="activeTab === 'rank'" class="rank-grid">
      <div class="card">
        <h3 class="card-title">销售额完成率排名</h3>
        <div v-if="!ranking.sales_ranking.length" class="empty">本月暂无设定目标的人员。</div>
        <ol v-else class="rank-list">
          <li v-for="(r, i) in ranking.sales_ranking" :key="r.owner">
            <span :class="['rank-no', { top: i < 3 }]">{{ i + 1 }}</span>
            <span class="rank-owner">{{ r.owner }}</span>
            <span class="rank-sub mono">{{ formatCurrency(r.actual_sales) }} / {{ formatCurrency(r.target_sales) }}</span>
            <span :class="['rank-pct', compClass(r.sales_completion)]">{{ pct(r.sales_completion) }}</span>
            <span v-if="achieved(r.sales_completion)" class="check" title="已达成"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
          </li>
        </ol>
      </div>
      <div class="card">
        <h3 class="card-title">利润额完成率排名</h3>
        <div v-if="!ranking.profit_ranking.length" class="empty">本月暂无设定目标的人员。</div>
        <ol v-else class="rank-list">
          <li v-for="(r, i) in ranking.profit_ranking" :key="r.owner">
            <span :class="['rank-no', { top: i < 3 }]">{{ i + 1 }}</span>
            <span class="rank-owner">{{ r.owner }}</span>
            <span class="rank-sub mono">{{ formatCurrency(r.actual_profit) }} / {{ formatCurrency(r.target_profit) }}</span>
            <span :class="['rank-pct', compClass(r.profit_completion)]">{{ pct(r.profit_completion) }}</span>
            <span v-if="achieved(r.profit_completion)" class="check" title="已达成"><svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg></span>
          </li>
        </ol>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { max-width: 1200px; margin: 0 auto; padding: 20px 4px 60px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.page-title { font-size: 20px; font-weight: 600; color: var(--ink); margin: 0; }
.page-sub { font-size: 13px; color: var(--ink-3); margin: 6px 0 0; }
.month-pick { font-size: 13px; color: var(--ink-3); display: inline-flex; align-items: center; gap: 8px; }
.month-pick input { font-family: inherit; font-size: 14px; padding: 7px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--ink); }

.tabs-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.seg { appearance: none; border: 1px solid var(--border); background: var(--surface); padding: 7px 14px; border-radius: 999px; font-family: inherit; font-size: 13px; color: var(--ink-2); cursor: pointer; }
.seg.on { background: var(--ink); color: #fff; border-color: var(--ink); }
.spacer { flex: 1; }

.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.card-title { font-size: 15px; font-weight: 600; margin: 0 0 12px; color: var(--ink); }
.readonly-hint { font-size: 12.5px; color: var(--ink-3); background: var(--bg-elev); padding: 8px 12px; border-radius: 8px; margin-bottom: 12px; }
.empty { padding: 32px; text-align: center; color: var(--ink-3); font-size: 13.5px; }

.table-wrap { overflow-x: auto; }
.grid { border-collapse: collapse; width: 100%; min-width: 960px; font-size: 14px; }
.grid th, .grid td { padding: 9px 11px; text-align: right; white-space: nowrap; border-bottom: 1px solid var(--divider); }
.grid th { font-weight: 500; color: var(--ink-3); font-size: 12.5px; text-align: right; }
.grid th:first-child, .grid td:first-child { text-align: left; }
.sticky-l { position: sticky; left: 0; background: var(--surface); z-index: 1; }
.owner { font-weight: 600; color: var(--ink); font-size: 14.5px; }
.ro { color: var(--ink-2); font-variant-numeric: tabular-nums; font-size: 14px; font-weight: 500; }
.num { width: 116px; text-align: right; font-family: inherit; font-size: 14px; padding: 6px 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--ink); font-variant-numeric: tabular-nums; }
.num:disabled { background: var(--bg-elev); color: var(--ink-2); }
.rate-input { display: inline-flex; align-items: center; gap: 4px; }
.rate-input .num { width: 78px; }
.suffix { color: var(--ink-3); font-size: 12.5px; }

/* completion pill + 达成 ✓ */
.comp { display: inline-flex; align-items: center; gap: 6px; }
.pill { display: inline-block; min-width: 62px; text-align: center; padding: 3px 10px; border-radius: 999px; font-size: 13px; font-weight: 500; font-variant-numeric: tabular-nums; }
.pill.ok { background: rgba(16, 185, 129, 0.14); color: #047857; }
.pill.warn { background: rgba(245, 158, 11, 0.16); color: #b45309; }
.pill.low { background: rgba(239, 68, 68, 0.13); color: #b91c1c; }
.pill.muted { background: var(--bg-elev); color: var(--ink-3); }
.check { display: inline-grid; place-items: center; width: 19px; height: 19px; border-radius: 999px; background: #10b981; flex: none; box-shadow: 0 1px 3px rgba(16, 185, 129, 0.4); }
.check svg { width: 12px; height: 12px; stroke: #fff; stroke-width: 3.4; fill: none; stroke-linecap: round; stroke-linejoin: round; }

.rank-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 760px) { .rank-grid { grid-template-columns: 1fr; } }
.rank-list { list-style: none; margin: 0; padding: 0; }
.rank-list li { display: flex; align-items: center; gap: 10px; padding: 11px 4px; border-bottom: 1px solid var(--divider); }
.rank-no { width: 24px; height: 24px; flex: none; display: grid; place-items: center; border-radius: 6px; font-size: 13px; font-weight: 600; color: var(--ink-3); background: var(--bg-elev); }
.rank-no.top { background: var(--ink); color: #fff; }
.rank-owner { font-size: 15px; color: var(--ink); font-weight: 600; }
.rank-sub { margin-left: auto; font-size: 12.5px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.rank-pct { width: 68px; text-align: right; font-size: 15.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
.rank-pct.ok { color: #047857; }
.rank-pct.warn { color: #b45309; }
.rank-pct.low { color: #b91c1c; }
.rank-pct.muted { color: var(--ink-3); }
</style>
