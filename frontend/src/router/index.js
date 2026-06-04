import { createRouter, createWebHashHistory } from "vue-router";
import { hasToken, getStoredUser } from "../api/client";
import { ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN } from "../stores/user";

// Roles allowed into /admin/users (backend access).
const BACKEND_ROLES = new Set([ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN]);
// Roles allowed to use the import feature.
const IMPORT_ROLES = new Set([ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN]);

const routes = [
  { path: "/login", name: "login", component: () => import("../views/Login.vue") },
  { path: "/", name: "dashboard", component: () => import("../views/Dashboard.vue") },
  {
    path: "/import",
    name: "import",
    component: () => import("../views/Import.vue"),
    meta: { requiresImport: true },
  },
  {
    path: "/admin/tenants",
    name: "tenants",
    component: () => import("../views/Tenants.vue"),
    meta: { requiresPlatform: true },
  },
  {
    path: "/admin/users",
    name: "users-admin",
    component: () => import("../views/Admin.vue"),
    meta: { requiresAdmin: true },
  },
  {
    // 人员目标完成情况 — admin manage + ranking (edit gated to super in-page).
    path: "/targets",
    name: "targets",
    component: () => import("../views/Targets.vue"),
    meta: { requiresAdmin: true },
  },
  {
    // 普通用户 self-view of their own goal progress.
    path: "/my-targets",
    name: "my-targets",
    component: () => import("../views/MyTargets.vue"),
  },
  // Convenience: /admin auto-routes by role
  { path: "/admin", redirect: () => {
      const u = getStoredUser();
      if (u?.role === ROLE_PLATFORM) return { name: "tenants" };
      return { name: "users-admin" };
    }
  },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

router.beforeEach((to) => {
  if (to.name !== "login" && !hasToken()) return { name: "login" };
  if (to.name === "login" && hasToken()) {
    const u = getStoredUser();
    if (u?.role === ROLE_PLATFORM) return { name: "tenants" };
    return { name: "dashboard" };
  }
  const u = getStoredUser();
  if (to.meta?.requiresPlatform && u?.role !== ROLE_PLATFORM) return { name: "dashboard" };
  if (to.meta?.requiresAdmin) {
    if (!u || !BACKEND_ROLES.has(u.role)) {
      return { name: "dashboard" };
    }
  }
  if (to.meta?.requiresImport) {
    if (!u || !IMPORT_ROLES.has(u.role)) {
      return { name: "dashboard" };
    }
  }
  // Platform admin has no tenant data — keep them out of tenant-scoped views.
  if (u?.role === ROLE_PLATFORM && ["dashboard", "import", "targets", "my-targets"].includes(to.name)) {
    return { name: "tenants" };
  }
});

export default router;
