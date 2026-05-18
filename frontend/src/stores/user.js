import { defineStore } from "pinia";
import { fetchMe, login as apiLogin } from "../api/auth";
import {
  clearSession, getStoredTenant, getStoredUser,
  setStoredTenant, setStoredUser, setToken,
} from "../api/client";

export const ROLE_PLATFORM = "platform_admin";
export const ROLE_TENANT_ADMIN = "tenant_admin";
export const ROLE_TENANT_USER = "tenant_user";

export const useUserStore = defineStore("user", {
  state: () => ({
    user: getStoredUser(),
    tenant: getStoredTenant(),
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    isPlatformAdmin: (s) => s.user?.role === ROLE_PLATFORM,
    isTenantAdmin: (s) => s.user?.role === ROLE_TENANT_ADMIN,
    isAdmin: (s) => s.user?.role === ROLE_PLATFORM || s.user?.role === ROLE_TENANT_ADMIN,
  },
  actions: {
    async login(username, password) {
      const data = await apiLogin(username, password);
      setToken(data.token);
      setStoredUser(data.user);
      setStoredTenant(data.tenant || null);
      this.user = data.user;
      this.tenant = data.tenant || null;
      return data.user;
    },
    async refresh() {
      try {
        const data = await fetchMe();
        this.user = data.user;
        this.tenant = data.tenant || null;
        setStoredUser(this.user);
        setStoredTenant(this.tenant);
      } catch (_) {
        this.logout();
      }
    },
    logout() {
      clearSession();
      this.user = null;
      this.tenant = null;
    },
  },
});
