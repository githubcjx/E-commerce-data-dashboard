import { defineStore } from "pinia";
import {
  fetchKpi, fetchTrend, fetchCategory, fetchFilters,
  getLayout, saveLayout,
} from "../api/dashboard";
import { listDepartments } from "../api/departments";

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
    // Top filter — drives EVERYTHING: KPI range, category table range, AND
    // trend chart range + bucketing. The dashboard reads as one slice of
    // time, no more independent "trend has its own view" weirdness.
    // Picker shape per tab: 日/月/年 = start + end; 周 = start week + end
    // week. Clicking a tab snaps the range to "this period".
    topGranularity: "day",       // day | week | month | year
    startDate: todayStr(),
    endDate: todayStr(),
    // Multi-select pickers. Empty array = 全部 (no filter); array of values
    // = WHERE col IN (...) on the backend.
    shopCodes: [],
    owners: [],
    categories: [],

    activeMetric: "sales",
    panelOrder: DEFAULT_ORDER.slice(),
    sectionOrder: DEFAULT_SECTIONS.slice(),

    kpiItems: [],
    trendPoints: [],
    trendGranularityServed: "day",
    categoryRows: [],
    filters: { shops: [], owners: [], categories: [], date_min: null, date_max: null },

    // Period labels surfaced into the UI (KPI cards say "对比 5.1~5.7")
    currentLabel: "",
    previousLabel: "",

    // 部门视角 picker — picks which department's view-shops to restrict
    // the dashboard to. null = no restriction.
    viewDepartmentId: null,
    // Full department list (id, name, view_shops). Used to filter the shop
    // dropdown when a 部门视角 is selected.
    departmentOptions: [],

    loading: false,
  }),
  getters: {
    // Shared range/filter params — granularity is added per-call by callers.
    // Multi-select arrays are serialized as comma-separated strings; the
    // backend treats an empty / "all" value as "no filter".
    _baseParams(state) {
      const csv = (arr) => (arr && arr.length ? arr.join(",") : "all");
      const p = {
        start_date: state.startDate,
        end_date: state.endDate,
        shop_code: csv(state.shopCodes),
        owner: csv(state.owners),
        category: csv(state.categories),
      };
      if (state.viewDepartmentId != null) p.view_department_id = state.viewDepartmentId;
      return p;
    },
    // Shops the user can currently pick from the 店铺 multi-select.
    // - 部门视角 set → only that department's view_shops
    // - otherwise   → all shops in this tenant
    availableShops(state) {
      if (state.viewDepartmentId == null) return state.filters.shops || [];
      const dept = state.departmentOptions.find((d) => d.id === state.viewDepartmentId);
      if (!dept) return [];
      const codes = new Set((dept.view_shops || []).map((s) => s.shop_code));
      return (state.filters.shops || []).filter((s) => codes.has(s.code));
    },
  },
  actions: {
    async loadFilters() {
      try { this.filters = await fetchFilters(); } catch (_) { /* keep empty */ }
    },
    async loadDepartments() {
      // Super-admin's "以部门视角查看" picker needs the tenant's department
      // list. Plain users don't see the picker — but loading is harmless and
      // they may still want to know the labels in the future. Failure is
      // non-fatal (e.g. tenant_user is forbidden by the backend).
      try {
        this.departmentOptions = await listDepartments();
      } catch (_) { this.departmentOptions = []; }
    },
    async loadKpi() {
      const granularity = kpiSparklineGranularity(this.startDate, this.endDate);
      const data = await fetchKpi({ ...this._baseParams, granularity });
      this.kpiItems = data.items || [];
      this.currentLabel = data.current_label || "";
      this.previousLabel = data.previous_label || "";
    },
    async loadTrend() {
      // Trend chart now mirrors the top filter exactly — same range, same
      // bucketing. No separate decisions, no highlight overlay.
      const data = await fetchTrend({
        ...this._baseParams,
        granularity: this.topGranularity,
        metric: this.activeMetric,
      });
      this.trendPoints = data.points || [];
      this.trendGranularityServed = data.granularity || this.topGranularity;
    },
    async loadCategory() {
      const {
        start_date, end_date, shop_code, owner, category, view_department_id,
      } = this._baseParams;
      const params = { start_date, end_date, shop_code, owner, category };
      if (view_department_id != null) params.view_department_id = view_department_id;
      this.categoryRows = await fetchCategory(params);
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
          const cleaned = parsed.order.filter((k) => known.has(k));
          const missing = DEFAULT_ORDER.filter((k) => !cleaned.includes(k));
          this.panelOrder = [...cleaned, ...missing];
        }
        if (Array.isArray(parsed.sections)) this.sectionOrder = parsed.sections;
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
        topGranularity: this.topGranularity,
      }));
    },
    resetLayout() {
      this.panelOrder = DEFAULT_ORDER.slice();
      this.sectionOrder = DEFAULT_SECTIONS.slice();
      this.persistLayout();
    },
    setActiveMetric(k) {
      // Click a KPI card → trend chart redraws for that metric. Range, tab,
      // and filters stay put.
      this.activeMetric = k;
      this.loadTrend();
    },
    async setTopGranularity(g) {
      // Top tab click: switch granularity AND snap to "this period". Trend
      // chart re-buckets along with the range change.
      this.topGranularity = g;
      const [s, e] = defaultRangeFor(g);
      this.startDate = s;
      this.endDate = e;
      await Promise.all([this.persistLayout(), this.loadAll()]);
    },
    async setRange(start, end) {
      // Picker change. Caller handles swap/clamp; we store + reload (trend
      // included — chart now follows the user's range exactly).
      this.startDate = start;
      this.endDate = end;
      await this.loadAll();
    },
    async setViewDepartmentId(id) {
      // Picking a 部门视角 limits dashboard data to that department's
      // view-shops. Drop any currently-selected shop codes that aren't
      // in the new visible set, since they'd silently disappear from
      // the dropdown anyway.
      this.viewDepartmentId = id == null ? null : Number(id);
      const shops = this.availableShops;
      const visibleCodes = new Set(shops.map((s) => s.code));
      this.shopCodes = this.shopCodes.filter((c) => visibleCodes.has(c));
      await this.loadAll();
    },
  },
});
