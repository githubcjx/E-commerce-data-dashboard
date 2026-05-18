import axios from "axios";

const TOKEN_KEY = "ec_dashboard.token.v1";
const USER_KEY = "ec_dashboard.user.v2";
const TENANT_KEY = "ec_dashboard.tenant.v1";

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}
export function getToken() { return localStorage.getItem(TOKEN_KEY) || ""; }
export function hasToken() { return !!getToken(); }

export function setStoredUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
  else localStorage.removeItem(USER_KEY);
}
export function getStoredUser() {
  try { return JSON.parse(localStorage.getItem(USER_KEY) || "null"); }
  catch (_) { return null; }
}

export function setStoredTenant(tenant) {
  if (tenant) localStorage.setItem(TENANT_KEY, JSON.stringify(tenant));
  else localStorage.removeItem(TENANT_KEY);
}
export function getStoredTenant() {
  try { return JSON.parse(localStorage.getItem(TENANT_KEY) || "null"); }
  catch (_) { return null; }
}

export function clearSession() {
  setToken("");
  setStoredUser(null);
  setStoredTenant(null);
}

const client = axios.create({ baseURL: "", timeout: 60000 });

client.interceptors.request.use((cfg) => {
  const t = getToken();
  if (t) cfg.headers.Authorization = `Bearer ${t}`;
  return cfg;
});

client.interceptors.response.use(
  (res) => {
    const body = res.data;
    if (body && typeof body === "object" && "code" in body) {
      if (body.code !== 0) return Promise.reject(new Error(body.msg || "请求失败"));
      return body.data;
    }
    return body;
  },
  (err) => {
    if (err.response?.status === 401) {
      clearSession();
      if (!location.hash.includes("/login")) location.hash = "#/login";
    }
    const msg = err.response?.data?.detail || err.message || "网络错误";
    return Promise.reject(new Error(msg));
  }
);

export default client;
