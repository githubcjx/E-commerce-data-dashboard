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

// Default time window: today (top filter defaults to "日 · 今天").
function todayStr() { return new Date().toISOString().slice(0, 10); }
function toIso(d) {
  // Local-time ISO date (avoid the UTC drift toISOString() would introduce
  // for dates near midnight).
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ISO week start = Monday in China-style calendars.
function startOfWeek(d) {
  const x = new Date(d);
  const wd = (x.getDay() + 6) % 7; // 0 = Monday
  x.setDate(x.getDate() - wd);
  return x;
}
function endOfWeek(d) {
  const s = startOfWeek(d);
  s.setDate(s.getDate() + 6);
  return s;
}
function startOfMonth(d) { return new Date(d.getFullYear(), d.getMonth(), 1); }
function endOfMonth(d)   { return new Date(d.getFullYear(), d.getMonth() + 1, 0); }
function startOfYear(d)  { return new Date(d.getFullYear(), 0, 1); }
function endOfYear(d)    { return new Date(d.getFullYear(), 11, 31); }

// "this period" for each top-granularity. Returns ISO date strings.
function defaultRangeFor(top) {
  const now = new Date();
  if (top === "week")  return [toIso(startOfWeek(now)),  toIso(endOfWeek(now))];
  if (top === "month") return [toIso(startOfMonth(now)), toIso(endOfMonth(now))];
  if (top === "year")  return [toIso(startOfYear(now)),  toIso(endOfYear(now))];
  return [todayStr(), todayStr()]; // day
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
    // Top filter: which "period" the user is looking at. Picks the shape of
    // the date picker AND the default range when the tab is clicked. The
    // user can still adjust the picker to broaden the selection (except for
    // 周 — that one is single-week by design).
    topGranularity: "day",       // day | week | month | year
    startDate: todayStr(),
    endDate: todayStr(),
    // Trend chart's own bucketing — controlled inside the trend panel.
    // Independent of topGranularity above.
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
        if (typeof parsed.topGranularity === "string" &&
            ["day", "week", "month", "year"].includes(parsed.topGranularity)) {
          this.topGranularity = parsed.topGranularity;
          // Snap range to current "this period" for the persisted top tab —
          // otherwise the stored range may be stale (yesterday on a 日 tab,
          // last week on 周, etc.) and the user lands on the wrong slice.
          const [s, e] = defaultRangeFor(parsed.topGranularity);
          this.startDate = s;
          this.endDate = e;
        }
      } catch (_) { /* ignore */ }
    },
    async persistLayout() {
      await saveLayout(JSON.stringify({
        order: this.panelOrder,
        sections: this.sectionOrder,
        subtractFixed: this.subtractFixed,
        trendGranularity: this.trendGranularity,
        topGranularity: this.topGranularity,
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
    async setTopGranularity(g) {
      // Top tab click: switch granularity AND snap to "this period" so the
      // user lands on today / this-week / this-month / this-year.
      this.topGranularity = g;
      const [s, e] = defaultRangeFor(g);
      this.startDate = s;
      this.endDate = e;
      await Promise.all([this.persistLayout(), this.loadAll()]);
    },
    async setRange(start, end) {
      // Picker change. Caller is responsible for swap/clamp logic, we just
      // store + reload.
      this.startDate = start;
      this.endDate = end;
      await this.loadAll();
    },
    async setSubtractFixed(v) {
      this.subtractFixed = !!v;
      await Promise.all([this.persistLayout(), this.loadAll()]);
    },
  },
});
