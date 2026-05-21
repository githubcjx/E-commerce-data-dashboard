import { defineStore } from "pinia";
import {
  fetchKpi, fetchTrend, fetchCategory, fetchFilters,
  getLayout, saveLayout, getTenantConfig,
} from "../api/dashboard";

// 8 metrics. companyProfitRate is new; refundRate keeps the same key but its
// display label changes to 发货退款率 (label comes from the API).
const DEFAULT_ORDER = [
  "sales", "profit", "profitRate", "companyProfitRate",
  "grossMargin", "refundRate", "shipPct", "adPct",
];
const DEFAULT_SECTIONS = ["trend", "categoryTable"];

// Default time window: last 30 days ending today.
function todayStr() { return new Date().toISOString().slice(0, 10); }
function daysAgoStr(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

// Sparklines on KPI cards just want "some" series points. We bucket
// adaptively so a 5-year range doesn't crush 1800 daily dots into 200px,
// and a 7-day range doesn't degenerate to a flat single bar.
function kpiSparklineGranularity(startStr, endStr) {
  const days = Math.max(1, Math.round(
    (new Date(endStr).getTime() - new Date(startStr).getTime()) / 86400000
  ) + 1);
  if (days <= 90) return "day";    // ≤ 3 months → daily
  if (days <= 730) return "week";  // ≤ 2 years → weekly
  return "month";                  // beyond → monthly
}

export const useDashboardStore = defineStore("dashboard", {
  state: () => ({
    // Range filter (replaces the single endDate)
    startDate: daysAgoStr(29),
    endDate: todayStr(),
    // Trend chart's own bucketing — controlled inside the trend panel.
    // Does NOT affect the top filter or the KPI cards above.
    trendGranularity: "day",     // day | week | month | year
    shopCode: "all",
    owner: "all",
    category: "all",
    subtractFixed: true,          // 公司利润率 是否减去固定利润率

    activeMetric: "sales",
    panelOrder: DEFAULT_ORDER.slice(),
    sectionOrder: DEFAULT_SECTIONS.slice(),

    kpiItems: [],
    trendPoints: [],
    trendGranularityServed: "day", // granularity the current trendPoints were fetched for
    categoryRows: [],
    filters: { shops: [], owners: [], categories: [] },

    // Period labels surfaced into the UI (KPI cards say "对比 5.1~5.7")
    currentLabel: "",
    previousLabel: "",
    fixedProfitRate: 0.13,        // server-fetched per tenant

    loading: false,
  }),
  getters: {
    // Shared range/filter params — granularity is added per-call by callers.
    _baseParams(state) {
      return {
        start_date: state.startDate,
        end_date: state.endDate,
        shop_code: state.shopCode,
        owner: state.owner,
        category: state.category,
        subtract_fixed: state.subtractFixed,
      };
    },
  },
  actions: {
    async loadFilters() {
      try { this.filters = await fetchFilters(); } catch (_) { /* keep empty */ }
    },
    async loadTenantConfig() {
      try {
        const cfg = await getTenantConfig();
        if (cfg && typeof cfg.fixed_profit_rate === "number") {
          this.fixedProfitRate = cfg.fixed_profit_rate;
        }
      } catch (_) { /* not fatal */ }
    },
    async loadKpi() {
      // Sparklines auto-bucket by range; independent from trend chart.
      const granularity = kpiSparklineGranularity(this.startDate, this.endDate);
      const data = await fetchKpi({ ...this._baseParams, granularity });
      this.kpiItems = data.items || [];
      this.currentLabel = data.current_label || "";
      this.previousLabel = data.previous_label || "";
      if (typeof data.fixed_profit_rate === "number") {
        this.fixedProfitRate = data.fixed_profit_rate;
      }
    },
    async loadTrend() {
      // Trend uses the user-chosen granularity from the trend panel.
      const data = await fetchTrend({
        ...this._baseParams,
        granularity: this.trendGranularity,
        metric: this.activeMetric,
      });
      this.trendPoints = data.points || [];
      this.trendGranularityServed = data.granularity || this.trendGranularity;
    },
    async loadCategory() {
      const { start_date, end_date, shop_code, owner, subtract_fixed } = this._baseParams;
      this.categoryRows = await fetchCategory({ start_date, end_date, shop_code, owner, subtract_fixed });
    },
    async loadAll() {
      this.loading = true;
      try {
        await Promise.all([this.loadKpi(), this.loadTrend(), this.loadCategory()]);
      } finally {
        this.loading = false;
      }
    },
    async loadLayout() {
      try {
        const data = await getLayout();
        const parsed = JSON.parse(data.layout_json);
        if (Array.isArray(parsed.order)) {
          const known = new Set(DEFAULT_ORDER);
          // Keep the user's saved order for keys we still know, and append
          // any new keys (e.g. companyProfitRate after upgrade) at the end.
          const cleaned = parsed.order.filter((k) => known.has(k));
          const missing = DEFAULT_ORDER.filter((k) => !cleaned.includes(k));
          this.panelOrder = [...cleaned, ...missing];
        }
        if (Array.isArray(parsed.sections)) this.sectionOrder = parsed.sections;
        if (typeof parsed.subtractFixed === "boolean") this.subtractFixed = parsed.subtractFixed;
        if (typeof parsed.trendGranularity === "string" &&
            ["day", "week", "month", "year"].includes(parsed.trendGranularity)) {
          this.trendGranularity = parsed.trendGranularity;
        }
      } catch (_) { /* ignore */ }
    },
    async persistLayout() {
      await saveLayout(JSON.stringify({
        order: this.panelOrder,
        sections: this.sectionOrder,
        subtractFixed: this.subtractFixed,
        trendGranularity: this.trendGranularity,
      }));
    },
    resetLayout() {
      this.panelOrder = DEFAULT_ORDER.slice();
      this.sectionOrder = DEFAULT_SECTIONS.slice();
      this.persistLayout();
    },
    setActiveMetric(k) {
      // Click a KPI card → trend chart redraws for that metric. Granularity
      // and filters stay put.
      this.activeMetric = k;
      this.loadTrend();
    },
    async setTrendGranularity(g) {
      this.trendGranularity = g;
      // Only the trend chart reloads — KPI cards & category table don't
      // depend on this control.
      await Promise.all([this.persistLayout(), this.loadTrend()]);
    },
    async setSubtractFixed(v) {
      this.subtractFixed = !!v;
      await Promise.all([this.persistLayout(), this.loadAll()]);
    },
  },
});
