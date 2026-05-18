/* global window */
// =========================================================================
// data.jsx — demo dataset that mirrors the prototype screenshot
// =========================================================================

const METRIC_DEFS = [
  { key: "sales",        label: "销售额",       format: "currency",    higherIsBetter: true  },
  { key: "orders",       label: "订单量",       format: "int",         higherIsBetter: true  },
  { key: "refundRate",   label: "退款率",       format: "percent",     higherIsBetter: false },
  { key: "grossMargin",  label: "毛利率",       format: "percent",     higherIsBetter: true  },
  { key: "profit",       label: "利润额",       format: "currency",    higherIsBetter: true  },
  { key: "profitRate",   label: "利润率",       format: "percent",     higherIsBetter: true  },
  { key: "shipPct",      label: "快递费用占比", format: "percent",     higherIsBetter: false },
  { key: "adPct",        label: "营销费用占比", format: "percent",     higherIsBetter: false },
];

// 10-day series (2026-05-01 → 2026-05-10) — designed to match the screenshot numbers
const DAILY = [
  { date: "2026-05-01", sales: 1380.4,  orders: 0, refundRate: 28.4, grossMargin: 82.1,  profit:  120.0, profitRate:  8.7, shipPct: 10.9, adPct: 62.3 },
  { date: "2026-05-02", sales: 2680.1,  orders: 0, refundRate: 36.2, grossMargin: 79.4,  profit:  -80.4, profitRate: -3.1, shipPct: 11.4, adPct: 71.8 },
  { date: "2026-05-03", sales: 2860.5,  orders: 0, refundRate: 41.3, grossMargin: 76.2,  profit: -310.2, profitRate: -10.8, shipPct: 11.2, adPct: 78.5 },
  { date: "2026-05-04", sales: 2740.0,  orders: 0, refundRate: 38.9, grossMargin: 77.8,  profit: -210.6, profitRate:  -7.9, shipPct: 11.0, adPct: 74.1 },
  { date: "2026-05-05", sales: 2738.6,  orders: 0, refundRate: 33.4, grossMargin: 80.6,  profit:  -60.9, profitRate:  -2.4, shipPct: 11.3, adPct: 70.2 },
  { date: "2026-05-06", sales: 2018.2,  orders: 0, refundRate: 32.1, grossMargin: 81.4,  profit:  -10.1, profitRate:  -0.5, shipPct: 12.2, adPct: 66.9 },
  { date: "2026-05-07", sales: 2810.7,  orders: 0, refundRate: 39.8, grossMargin: 73.5,  profit: -420.7, profitRate: -14.9, shipPct: 11.9, adPct: 79.3 },
  { date: "2026-05-08", sales: 2820.4,  orders: 0, refundRate: 44.6, grossMargin: 64.8,  profit: -610.4, profitRate: -22.4, shipPct: 12.1, adPct: 86.0 },
  { date: "2026-05-09", sales: 2055.8,  orders: 0, refundRate: 45.1, grossMargin: 56.2,  profit: -880.6, profitRate: -42.8, shipPct: 11.8, adPct: 95.4 },
  { date: "2026-05-10", sales: 2508.65, orders: 0, refundRate: 42.94, grossMargin: 50.33, profit: -1809.7, profitRate: -72.14, shipPct: 11.83, adPct: 105.29 },
];

const PREV_PERIOD = {
  sales: 2054.8,
  orders: 0,
  refundRate: 35.56,
  grossMargin: 77.95,
  profit: -266.82,
  profitRate: -12.99,
  shipPct: 11.47,
  adPct: 72.61,
};

// Default panel order (drag-reorderable)
const DEFAULT_PANEL_ORDER = [
  "sales", "orders", "refundRate", "grossMargin",
  "profit", "profitRate", "shipPct", "adPct",
];

// Category breakdown
const CATEGORIES = [
  { name: "家居家纺",    sales: 942.30,   profit:  -421.2, orders: 0, grossMargin: 48.2, refundRate: 51.3 },
  { name: "美妆个护",    sales: 612.50,   profit:  -298.1, orders: 0, grossMargin: 53.6, refundRate: 38.4 },
  { name: "服饰鞋包",    sales: 481.85,   profit:  -512.6, orders: 0, grossMargin: 44.9, refundRate: 47.9 },
  { name: "数码配件",    sales: 286.40,   profit:  -341.0, orders: 0, grossMargin: 39.2, refundRate: 36.5 },
  { name: "母婴玩具",    sales: 185.60,   profit:  -236.8, orders: 0, grossMargin: 58.4, refundRate: 32.1 },
];

// Shops / owners
const SHOPS  = ["全部", "旗舰店 · 天猫", "旗舰店 · 京东", "专营店 · 抖音", "海外仓 · 速卖通"];
const OWNERS = ["全部", "陈雨晴", "周明", "林婉", "Daniel Park"];
const CATS   = ["全部", "家居家纺", "美妆个护", "服饰鞋包", "数码配件", "母婴玩具"];

// Upload history (mock)
const UPLOAD_HISTORY = [
  { name: "2026-05_交易明细.xlsx",     size: "1.2 MB", rows: 4218, when: "2026-05-10 09:42" },
  { name: "2026-05_退款流水.xlsx",     size: "284 KB", rows:  812, when: "2026-05-10 09:43" },
  { name: "2026-04_汇总_v2.xlsx",      size: "2.6 MB", rows: 9214, when: "2026-05-01 11:08" },
];

// ---------- formatters ----------
function formatValue(v, fmt) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (fmt === "currency") {
    return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (fmt === "percent") {
    return v.toFixed(2) + "%";
  }
  if (fmt === "int") {
    return Math.round(v).toLocaleString("en-US");
  }
  return String(v);
}

function formatDelta(curr, prev, higherIsBetter) {
  if (prev === 0 && curr === 0) return { sign: "flat", text: "0.00%", arrow: "→" };
  if (prev === 0) return { sign: "flat", text: "—", arrow: "→" };
  const pct = ((curr - prev) / Math.abs(prev)) * 100;
  if (Math.abs(pct) < 0.005) return { sign: "flat", text: "0.00%", arrow: "→" };
  const isUp = pct > 0;
  // For metrics where lower is better, "up" is bad.
  const good = higherIsBetter ? isUp : !isUp;
  return {
    sign: good ? "up" : "down",
    text: (pct > 0 ? "+" : "") + pct.toFixed(2) + "%",
    arrow: isUp ? "↑" : "↓",
  };
}

Object.assign(window, {
  METRIC_DEFS,
  DAILY,
  PREV_PERIOD,
  DEFAULT_PANEL_ORDER,
  CATEGORIES,
  SHOPS,
  OWNERS,
  CATS,
  UPLOAD_HISTORY,
  formatValue,
  formatDelta,
});
