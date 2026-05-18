import client from "./client";

export function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  return client.post("/api/import/upload", fd);
}

export const getBatch = (id) => client.get(`/api/import/batches/${id}`);
export const listBatches = (limit = 30) => client.get("/api/import/batches", { params: { limit } });
export const rollbackBatch = (id) => client.delete(`/api/import/batches/${id}`);
