import client from "./client";

// 人员目标完成情况. Rates (target_profit_rate, *_completion) are decimals
// (0.15 = 15%) — the views format them for display.
export const listTargets = (year_month) =>
  client.get("/api/targets", { params: { year_month } });
export const saveTargets = (year_month, items) =>
  client.put("/api/targets", { year_month, items });
export const fetchRanking = (year_month) =>
  client.get("/api/targets/ranking", { params: { year_month } });
export const fetchMyTargets = (year_month) =>
  client.get("/api/targets/me", { params: { year_month } });
export const fetchReminder = () => client.get("/api/targets/reminder");
