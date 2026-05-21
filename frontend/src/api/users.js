import client from "./client";

export const listUsers = (tenantId) => client.get("/api/users", { params: tenantId ? { tenant_id: tenantId } : {} });
export const createUser = (body) => client.post("/api/users", body);
export const updateUser = (id, body) => client.put(`/api/users/${id}`, body);
export const deleteUser = (id) => client.delete(`/api/users/${id}`);
// Owner names available within a tenant — used by the data-scope picker.
export const listTenantOwners = (tenantId) =>
  client.get("/api/users/owners", { params: tenantId ? { tenant_id: tenantId } : {} });
