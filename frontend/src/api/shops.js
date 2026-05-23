import client from "./client";

// Per-shop list (used by 部门管理 picker + dashboard).
export const listShops = (tenantId) =>
  client.get("/api/shops", { params: tenantId ? { tenant_id: tenantId } : {} });

export const updateShop = (shopCode, body, tenantId) =>
  client.patch(`/api/shops/${encodeURIComponent(shopCode)}`, body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

// Fee-group view (used by 店铺管理). One row per distinct
// fee_group_name; the shops[] inside is the member list.
export const listFeeGroups = (tenantId) =>
  client.get("/api/shops/fee-groups", { params: tenantId ? { tenant_id: tenantId } : {} });

// Create or update a fee group. body shape:
//   { original_name?, name, per_capita_share, ship_service_tax_rate, shop_codes }
// original_name omitted/null = create. Provided = edit (also reconciles
// members — shops in the old group but not in the new shop_codes get
// their fee config cleared).
export const saveFeeGroup = (body, tenantId) =>
  client.post("/api/shops/fee-groups", body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

export const deleteFeeGroup = (name, tenantId) =>
  client.delete(`/api/shops/fee-groups/${encodeURIComponent(name)}`, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
