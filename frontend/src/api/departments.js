import client from "./client";

// Tenant scope is implicit from the JWT for non-platform users. Platform
// admins must pass tenantId so the backend knows which company to operate on.
export const listDepartments = (tenantId) =>
  client.get("/api/departments", { params: tenantId ? { tenant_id: tenantId } : {} });

export const getDepartment = (id) => client.get(`/api/departments/${id}`);

export const createDepartment = (body) => client.post("/api/departments", body);

export const updateDepartment = (id, body) => client.patch(`/api/departments/${id}`, body);

export const deleteDepartment = (id) => client.delete(`/api/departments/${id}`);
