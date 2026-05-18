import { defineStore } from "pinia";
import { fetchKpi, fetchTrend, fetchCategory, fetchFilters, getLayout, saveLayout } from "../api/dashboard";

const DEFAULT_ORDER = ["sales", "refundRate", "grossMargin", "profit", "profitRate", "shipPct", "adPct"];
const DEFAULT_SECTIONS = ["trend", "categoryTable"];

export const useDashboardStore = defineStore("dashboard", {
  state: () => ({
    endDate: new Date().toISOString().slice(0, 10),
    granularity: "day",
    shopCode: "all",
    owner: "all",
    category: "all",
    activeMetric: "sales",
    panelOrder: DEFAULT_ORDER.slice(),
    sectionOrder: DEFAULT_SECTIONS.slice(),
    kpiItems: [],
    trendPoints: [],
    categoryRows: [],
    filters: { shops: [], owners: [], categories: [] },
    loading: false,
  }),
  getters: {
    params(state) {
      return {
        end_date: state.endDate,
        granularity: state.granularity,
        shop_code: state.shopCode,
        owner: state.owner,
        category: state.category,
      };
    },
  },
  actions: {
    async loadFilters() {
      try { this.filters = await fetchFilters(); } catch (_) { /* keep empty */ }
    },
    async loadKpi() {
      const data = await fetchKpi(this.params);
      this.kpiItems = data.items || [];
    },
    async loadTrend() {
      const data = await fetchTrend({ ...this.params, metric: this.activeMetric });
      this.trendPoints = data.points || [];
    },
    async loadCategory() {
      const { end_date, granularity, shop_code, owner } = this.params;
      this.categoryRows = await fetchCategory({ end_date, granularity, shop_code, owner });
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
        // Filter out unknown/removed keys (e.g. legacy "orders") and only
        // accept the layout if it covers every current metric.
        if (Array.isArray(parsed.order)) {
          const known = new Set(DEFAULT_ORDER);
          const cleaned = parsed.order.filter((k) => known.has(k));
          if (cleaned.length === DEFAULT_ORDER.length) this.panelOrder = cleaned;
        }
        if (Array.isArray(parsed.sections)) this.sectionOrder = parsed.sections;
      } catch (_) { /* ignore */ }
    },
    async persistLayout() {
      await saveLayout(JSON.stringify({ order: this.panelOrder, sections: this.sectionOrder }));
    },
    resetLayout() {
      this.panelOrder = DEFAULT_ORDER.slice();
      this.sectionOrder = DEFAULT_SECTIONS.slice();
      this.persistLayout();
    },
    setActiveMetric(k) {
      this.activeMetric = k;
      this.loadTrend();
    },
  },
});
