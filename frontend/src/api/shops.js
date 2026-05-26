import client from "./client";

// Per-shop list (used by 部门管理 picker + dashboard).
export const listShops = (tenantId) =>
  client.get("/api/shops", { params: tenantId ? { tenant_id: tenantId } : {} });

export const updateShop = (shopCode, body, tenantId) =>
  client.patch(`/api/shops/${encodeURIComponent(shopCode)}`, body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

// Fee-group view (used by 店铺管理). One row per distinct
// fee_group_name; the shops[] inside is the member list. Each row also
// surfaces the CURRENT calendar month's 固定费用 amount (or null when
// no row exists yet) so the table can show "本月" at a glance.
export const listFeeGroups = (tenantId) =>
  client.get("/api/shops/fee-groups", { params: tenantId ? { tenant_id: tenantId } : {} });

// Create or update a fee group. body shape:
//   { original_name?, name, ship_service_tax_rate, shop_codes }
// original_name omitted/null = create. Provided = edit (also reconciles
// members — shops in the old group but not in the new shop_codes get
// their fee config cleared). Renames cascade to fee_group_monthly_cost
// so per-month history follows.
//
// NOTE: per_capita_share is GONE. 固定费用 is now per-month, edited via
// the separate listMonthlyCosts / saveMonthlyCosts endpoints.
export const saveFeeGroup = (body, tenantId) =>
  client.post("/api/shops/fee-groups", body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

export const deleteFeeGroup = (name, tenantId) =>
  client.delete(`/api/shops/fee-groups/${encodeURIComponent(name)}`, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

// ---------------------------------------------------------------------------
// Per-month 固定费用 — list + batch save
// ---------------------------------------------------------------------------

// Returns { fee_group_name, rows: [{year_month, amount, is_current_month}] }.
// The backend guarantees one row per month from the tenant's earliest
// imported data month through the current calendar month (ascending).
// The frontend reverses for display so the most recent month is on top.
export const listMonthlyCosts = (name, tenantId) =>
  client.get(`/api/shops/fee-groups/${encodeURIComponent(name)}/monthly-costs`, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

// Atomic batch upsert. body = { items: [{year_month, amount}, ...] }.
// Sending only changed rows is fine; sending the whole list is also fine
// (the backend diffs against stored values).
export const saveMonthlyCosts = (name, items, tenantId) =>
  client.put(
    `/api/shops/fee-groups/${encodeURIComponent(name)}/monthly-costs`,
    { items },
    { params: tenantId ? { tenant_id: tenantId } : {} },
  );
