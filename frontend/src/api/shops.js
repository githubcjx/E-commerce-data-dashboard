import client from "./client";

export const listShops = (tenantId) =>
  client.get("/api/shops", { params: tenantId ? { tenant_id: tenantId } : {} });

export const updateShop = (shopCode, body, tenantId) =>
  client.patch(`/api/shops/${encodeURIComponent(shopCode)}`, body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });

// Apply (fee_department, per_capita_share, ship_service_tax_rate) to a
// set of shop_codes in one go. Used by the 店铺管理 dialog.
export const applyShopFeeBatch = (body, tenantId) =>
  client.post("/api/shops/fee-batch", body, {
    params: tenantId ? { tenant_id: tenantId } : {},
  });
