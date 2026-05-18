import client from "./client";

export const fetchKpi = (params) => client.get("/api/dashboard/kpi", { params });
export const fetchTrend = (params) => client.get("/api/dashboard/trend", { params });
export const fetchCategory = (params) => client.get("/api/dashboard/category", { params });
export const fetchFilters = () => client.get("/api/dashboard/filters");

export const getLayout = () => client.get("/api/layout");
export const saveLayout = (layout_json) => client.put("/api/layout", { layout_json });
