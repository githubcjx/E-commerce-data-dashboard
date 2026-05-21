<script setup>
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useUserStore } from "../stores/user";

const route = useRoute();
const router = useRouter();
const userStore = useUserStore();

const updatedAt = computed(() => {
  const d = new Date();
  return d.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" });
});

const isDashboard = computed(() => route.name === "dashboard");
const isImport = computed(() => route.name === "import");
const isAdminPage = computed(() => route.name === "tenants" || route.name === "users-admin");

const menuOpen = ref(false);

function roleLabel(role) {
  if (role === "platform_admin") return "平台管理员";
  if (role === "tenant_super_admin") return "超级管理员";
  if (role === "tenant_admin") return "管理员";
  return "普通用户";
}

function logout() {
  userStore.logout();
  router.push({ name: "login" });
}

function gotoAdmin() {
  menuOpen.value = false;
  router.push({ path: "/admin" });
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <span class="brand-mark">EC</span>
        <span class="brand-name">电商经营看板</span>
        <span class="brand-tag" v-if="userStore.tenant">· {{ userStore.tenant.name }}</span>
        <span class="brand-tag" v-else>· v1.0</span>
      </div>

      <div v-if="!userStore.isPlatformAdmin" class="tabs" role="tablist">
        <button :class="['tab', { 'is-active': isDashboard }]" @click="router.push({ name: 'dashboard' })">看板</button>
        <button :class="['tab', { 'is-active': isImport }]" @click="router.push({ name: 'import' })">导入</button>
      </div>

      <div class="topbar-right">
        <span class="status-dot" />
        <span>数据更新于 {{ updatedAt }}</span>
        <span class="topbar-divider" />
        <button
          v-if="userStore.isAdmin"
          :class="['btn sm', { primary: isAdminPage }]"
          @click="gotoAdmin"
          :title="userStore.isPlatformAdmin ? '后台 — 管理企业' : '后台 — 管理用户'"
        >后台</button>

        <div class="user-menu" @click.stop>
          <button class="user-chip" @click="menuOpen = !menuOpen">
            <span class="user-avatar">{{ (userStore.user?.username || "?").slice(0,1).toUpperCase() }}</span>
            <span class="mono">{{ userStore.user?.username || "未登录" }}</span>
            <span class="role-tag">{{ roleLabel(userStore.user?.role) }}</span>
          </button>
          <div v-if="menuOpen" class="user-pop">
            <div class="pop-meta">
              <div class="mono" style="font-size:13px">{{ userStore.user?.username }}</div>
              <div style="font-size:12px;color:var(--ink-4);margin-top:2px">{{ roleLabel(userStore.user?.role) }}</div>
              <div v-if="userStore.tenant" style="font-size:12px;color:var(--ink-3);margin-top:4px">
                所属企业：<span class="mono">{{ userStore.tenant.code }}</span> · {{ userStore.tenant.name }}
              </div>
            </div>
            <button class="pop-item" @click="logout">退出登录</button>
          </div>
        </div>
      </div>
    </div>
  </header>
</template>

<style scoped>
.user-menu { position: relative; }
.user-chip {
  appearance: none; border: 1px solid var(--border); background: var(--surface);
  display: inline-flex; align-items: center; gap: 8px;
  padding: 4px 10px 4px 4px; border-radius: 999px; cursor: pointer;
  font-family: inherit; font-size: 12.5px; color: var(--ink);
  transition: border-color .15s, background .15s;
}
.user-chip:hover { border-color: var(--border-strong); background: var(--surface-hover); }
.user-avatar {
  width: 22px; height: 22px; border-radius: 999px;
  background: var(--ink); color: #fff;
  display: grid; place-items: center;
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
}
.role-tag {
  font-size: 11px; color: var(--ink-3); padding: 2px 6px;
  background: var(--bg-elev); border-radius: 999px;
}
.user-pop {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 40;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; box-shadow: var(--shadow-pop);
  min-width: 240px; padding: 6px;
}
.pop-meta { padding: 10px 12px 10px; border-bottom: 1px solid var(--divider); }
.pop-item {
  appearance: none; border: 0; background: transparent; width: 100%; text-align: left;
  padding: 8px 12px; border-radius: 6px; font-family: inherit; font-size: 13px;
  color: var(--ink); cursor: pointer;
}
.pop-item:hover { background: var(--surface-hover); }
</style>
