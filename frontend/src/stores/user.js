import { defineStore } from "pinia";
import { fetchMe, login as apiLogin } from "../api/auth";
import {
  clearSession, getStoredTenant, getStoredUser,
  setStoredTenant, setStoredUser, setToken,
} from "../api/client";

export const ROLE_PLATFORM = "platform_admin";
export const ROLE_TENANT_SUPER = "tenant_super_admin";
export const ROLE_TENANT_ADMIN = "tenant_admin";
export const ROLE_TENANT_USER = "tenant_user";

// Roles that can see the /admin backend page.
const BACKEND_ROLES = new Set([ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN]);

export const useUserStore = defineStore("user", {
  state: () => ({
    user: getStoredUser(),
    tenant: getStoredTenant(),
  }),
  getters: {
    isLoggedIn: (s) => !!s.user,
    isPlatformAdmin: (s) => s.user?.role === ROLE_PLATFORM,
    // Tenant *super* admin — the original tenant boss.
    isTenantSuperAdmin: (s) => s.user?.role === ROLE_TENANT_SUPER,
    // Plain tenant admin — backend access, edit-only on 普通用户.
    isTenantPlainAdmin: (s) => s.user?.role === ROLE_TENANT_ADMIN,
    // Any backend-capable user (sees the 后台 link).
    isAdmin: (s) => BACKEND_ROLES.has(s.user?.role),
    // Can create / delete / change role / change scope.
    canManageUsers: (s) => s.user?.role === ROLE_PLATFORM || s.user?.role === ROLE_TENANT_SUPER,
    // Can use the import feature. 普通用户 are hidden from it entirely;
    // platform_admin has no own tenant so they can't import either.
    canImport: (s) => s.user?.role === ROLE_TENANT_SUPER || s.user?.role === ROLE_TENANT_ADMIN,
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
