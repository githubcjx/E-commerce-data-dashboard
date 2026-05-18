import { createRouter, createWebHashHistory } from "vue-router";
import { hasToken, getStoredUser } from "../api/client";
import { ROLE_PLATFORM, ROLE_TENANT_ADMIN } from "../stores/user";

const routes = [
  { path: "/login", name: "login", component: () => import("../views/Login.vue") },
  { path: "/", name: "dashboard", component: () => import("../views/Dashboard.vue") },
  { path: "/import", name: "import", component: () => import("../views/Import.vue") },
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
    if (!u || (u.role !== ROLE_PLATFORM && u.role !== ROLE_TENANT_ADMIN)) {
      return { name: "dashboard" };
    }
  }
  // Platform admin has no tenant data — keep them out of the dashboard/import views.
  if (u?.role === ROLE_PLATFORM && (to.name === "dashboard" || to.name === "import")) {
    return { name: "tenants" };
  }
});

export default router;
