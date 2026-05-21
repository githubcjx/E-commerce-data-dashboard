<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { listUsers, createUser, updateUser, deleteUser } from "../api/users";
import { getTenantConfig, updateTenantConfig } from "../api/dashboard";
import { useUserStore } from "../stores/user";
import { useUiStore } from "../stores/ui";

const userStore = useUserStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

const users = ref([]);
const loading = ref(false);

// 固定利润率配置（tenant_admin 可编辑、platform_admin 跨租户时不显示）
const cfg = ref({ fixed_profit_rate: 0.13 });
const cfgInput = ref("13");          // 显示成百分比（13 表示 13%）
const cfgSaving = ref(false);
const showCfg = computed(() => !userStore.isPlatformAdmin && userStore.user?.role === "tenant_admin");

async function loadCfg() {
  if (!showCfg.value) return;
  try {
    const data = await getTenantConfig();
    cfg.value = data;
    cfgInput.value = (Number(data.fixed_profit_rate) * 100).toFixed(2).replace(/\.?0+$/, "");
  } catch (e) { /* ignore */ }
}

async function saveCfg() {
  const pct = Number(cfgInput.value);
  if (!Number.isFinite(pct) || pct < 0 || pct >= 100) {
    ui.showToast("请输入 0-100 之间的数字", "error");
    return;
  }
  cfgSaving.value = true;
  try {
    const data = await updateTenantConfig({ fixed_profit_rate: pct / 100 });
    cfg.value = data;
    ui.showToast("已保存，看板将按新比例计算公司利润率", "success");
  } catch (e) {
    ui.showToast(e.message || "保存失败", "error");
  } finally {
    cfgSaving.value = false;
  }
}

// When platform_admin lands here from "/admin/tenants → 用户" they bring
// tenant_id/tenant_code/tenant_name in the query string. Otherwise it's the
// admin viewing their own tenant.
const targetTenantId = computed(() => {
  if (userStore.isPlatformAdmin) {
    return route.query.tenant_id ? Number(route.query.tenant_id) : null;
  }
  return userStore.tenant?.id || null;
});

const targetTenantLabel = computed(() => {
  if (userStore.isPlatformAdmin) {
    if (route.query.tenant_code) return `${route.query.tenant_code} · ${route.query.tenant_name || ""}`;
    return null;
  }
  return userStore.tenant ? `${userStore.tenant.code} · ${userStore.tenant.name}` : null;
});

const dialogOpen = ref(false);
const editing = ref(null);
const form = ref({ username: "", password: "", role: "tenant_user", display_name: "" });
const formError = ref("");

function roleLabel(role) {
  if (role === "platform_admin") return "平台管理员";
  if (role === "tenant_admin") return "管理员";
  return "普通用户";
}

function canEdit(target) {
  if (target.id === userStore.user?.id) return false;       // not self
  if (target.role === "platform_admin") return false;       // platform_admin off-limits here
  return true;
}
function canDelete(target) { return canEdit(target); }

async function refresh() {
  if (userStore.isPlatformAdmin && !targetTenantId.value) {
    users.value = [];
    return;
  }
  loading.value = true;
  try { users.value = await listUsers(targetTenantId.value); }
  catch (e) { ui.showToast(e.message || "加载失败", "error"); }
  finally { loading.value = false; }
}

function openCreate() {
  editing.value = null;
  form.value = { username: "", password: "", role: "tenant_user", display_name: "" };
  formError.value = "";
  dialogOpen.value = true;
}
function openEdit(u) {
  editing.value = u;
  form.value = { username: u.username, password: "", role: u.role, display_name: u.display_name || "" };
  formError.value = "";
  dialogOpen.value = true;
}

async function submit() {
  formError.value = "";
  try {
    if (editing.value) {
      const body = {};
      if (form.value.password) body.password = form.value.password;
      if (form.value.display_name !== (editing.value.display_name || "")) body.display_name = form.value.display_name;
      if (form.value.role !== editing.value.role) body.role = form.value.role;
      await updateUser(editing.value.id, body);
      ui.showToast("已更新", "success");
    } else {
      if (!form.value.username || !form.value.password) {
        formError.value = "账号和密码必填";
        return;
      }
      const body = {
        username: form.value.username,
        password: form.value.password,
        role: form.value.role,
        display_name: form.value.display_name || null,
      };
      // Platform admin creating users into a target tenant must specify it.
      if (userStore.isPlatformAdmin) body.tenant_id = targetTenantId.value;
      await createUser(body);
      ui.showToast("已新增", "success");
    }
    dialogOpen.value = false;
    await refresh();
  } catch (e) {
    formError.value = e.message || "保存失败";
  }
}

async function remove(u) {
  if (!confirm(`确认删除账号「${u.username}」？该用户的导入批次将保留（记录归零）。`)) return;
  try {
    await deleteUser(u.id);
    ui.showToast("已删除", "success");
    await refresh();
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

function backToTenants() {
  router.push({ name: "tenants" });
}

onMounted(async () => { await refresh(); await loadCfg(); });
watch(() => route.query.tenant_id, refresh);
</script>

<template>
  <section v-if="showCfg" class="panel" style="margin-bottom:16px">
    <header class="panel-head">
      <span class="panel-title">企业配置</span>
      <span class="panel-subtitle">仅企业管理员可见 · 影响看板的「公司利润率」计算</span>
    </header>
    <div style="padding:18px 22px">
      <div class="cfg-row">
        <label>
          固定利润率
          <span class="t-muted" style="font-size:12px;margin-left:6px">公司利润率 = 经营利润率 − 此值</span>
        </label>
        <div class="cfg-input">
          <input type="number" min="0" max="99.99" step="0.01" v-model="cfgInput" :disabled="cfgSaving" />
          <span class="suffix">%</span>
          <button class="btn primary sm" @click="saveCfg" :disabled="cfgSaving">{{ cfgSaving ? "保存中…" : "保存" }}</button>
        </div>
      </div>
      <div class="t-muted" style="font-size:12px;margin-top:8px">
        当前生效值：{{ (cfg.fixed_profit_rate * 100).toFixed(2).replace(/\.?0+$/, "") }}%。看板「公司利润率」卡片上的开关只控制当前用户是否减去此值，不影响这里保存的配置。
      </div>
    </div>
  </section>

  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">用户管理</span>
      <span class="panel-subtitle" v-if="targetTenantLabel">{{ targetTenantLabel }} · {{ users.length }} 个账号</span>
      <span class="panel-subtitle" v-else>共 {{ users.length }} 个账号</span>
      <div class="panel-actions">
        <button v-if="userStore.isPlatformAdmin" class="btn ghost sm" @click="backToTenants">← 返回企业列表</button>
        <button class="btn primary sm" @click="openCreate">+ 新增账号</button>
      </div>
    </header>
    <table class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">账号</th>
          <th style="text-align:left">显示名</th>
          <th style="text-align:left">角色</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}<span v-if="u.id === userStore.user?.id" class="tag" style="margin-left:8px">我</span></td>
          <td style="text-align:left">{{ u.display_name || '—' }}</td>
          <td style="text-align:left">
            <span :class="['tag', u.role === 'tenant_admin' ? 'success' : '']">{{ roleLabel(u.role) }}</span>
          </td>
          <td style="text-align:left" class="t-muted">{{ new Date(u.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button class="btn ghost sm" :disabled="!canEdit(u)" @click="openEdit(u)">编辑</button>
            <button class="btn ghost sm" :disabled="!canDelete(u)" @click="remove(u)" style="color:var(--neg)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !users.length">
          <td colspan="5" class="empty-state">暂无用户</td>
        </tr>
      </tbody>
    </table>
  </section>

  <div v-if="dialogOpen" class="modal-backdrop" @click.self="dialogOpen = false">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editing ? "编辑账号" : "新增账号" }}</span>
        <button class="btn ghost sm" @click="dialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field">
          <label>账号</label>
          <input :disabled="!!editing" v-model="form.username" placeholder="至少 2 个字符" />
        </div>
        <div class="field">
          <label>密码 <span v-if="editing" class="t-muted" style="font-size:11px">（留空则不修改）</span></label>
          <input type="password" v-model="form.password" placeholder="至少 6 位" />
        </div>
        <div class="field">
          <label>显示名</label>
          <input v-model="form.display_name" placeholder="可选" />
        </div>
        <div class="field">
          <label>角色</label>
          <select class="select" v-model="form.role">
            <option value="tenant_user">普通用户</option>
            <option value="tenant_admin">管理员</option>
          </select>
        </div>
        <div class="error">{{ formError }}</div>
      </div>
      <footer class="modal-foot">
        <button class="btn" @click="dialogOpen = false">取消</button>
        <button class="btn primary" @click="submit">保存</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 12px; color: var(--ink-3); font-weight: 500; }
.field input, .field select {
  appearance: none; border: 1px solid var(--border); border-radius: 8px;
  padding: 9px 12px; font-family: var(--font-sans); font-size: 14px; color: var(--ink);
  background: var(--surface);
}
.field input:focus, .field select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-line); }
.field input:disabled { background: var(--bg-elev); color: var(--ink-4); cursor: not-allowed; }

.modal-backdrop {
  position: fixed; inset: 0; background: rgba(20, 20, 15, 0.45);
  display: grid; place-items: center; z-index: 80; backdrop-filter: blur(4px);
}
.modal-card {
  width: 460px; max-width: calc(100vw - 32px);
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-pop);
  display: flex; flex-direction: column;
}
.modal-head, .modal-foot {
  padding: 14px 18px; display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid var(--divider);
}
.modal-foot { border-bottom: 0; border-top: 1px solid var(--divider); justify-content: flex-end; }
.modal-body { padding: 18px; }
.error { font-size: 12px; color: var(--neg); min-height: 16px; }

.cfg-row { display: flex; flex-direction: column; gap: 8px; }
.cfg-row > label { font-size: 13px; color: var(--ink-2); font-weight: 500; }
.cfg-input { display: flex; align-items: center; gap: 6px; }
.cfg-input input {
  width: 100px; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  font-family: var(--font-mono); font-size: 14px; color: var(--ink);
  background: var(--surface);
}
.cfg-input input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-line); }
.cfg-input .suffix { color: var(--ink-4); font-family: var(--font-mono); font-size: 13px; }
</style>
