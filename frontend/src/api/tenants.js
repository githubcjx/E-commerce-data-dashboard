import client from "./client";

export const listTenants = () => client.get("/api/tenants");
export const createTenant = (body) => client.post("/api/tenants", body);
export const updateTenant = (id, body) => client.put(`/api/tenants/${id}`, body);
export const deleteTenant = (id) => client.delete(`/api/tenants/${id}`);
