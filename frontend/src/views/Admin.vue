<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  listUsers, createUser, updateUser, deleteUser, listTenantOwners,
} from "../api/users";
import { getTenantConfig, updateTenantConfig } from "../api/dashboard";
import {
  useUserStore, ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN, ROLE_TENANT_USER,
} from "../stores/user";
import { useUiStore } from "../stores/ui";

const userStore = useUserStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

const users = ref([]);
const loading = ref(false);
const ownersAvailable = ref([]);   // 负责人 list for the scope multi-select

// ---------------------------------------------------------------------------
// Tenant config (固定利润率) — super_admin only.
// ---------------------------------------------------------------------------
const cfg = ref({ fixed_profit_rate: 0.13 });
const cfgInput = ref("13");
const cfgSaving = ref(false);
// Visible only to a tenant_super_admin viewing their own tenant. Platform
// admin sees the org-config panel in Tenants.vue (or directly via DB).
const showCfg = computed(() => userStore.isTenantSuperAdmin);

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

// ---------------------------------------------------------------------------
// Target tenant (platform_admin reaches here via query string; tenant users
// always see their own tenant).
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Permission helpers — mirror the backend rules so the UI doesn't offer
// actions the server will reject anyway.
// ---------------------------------------------------------------------------
const me = computed(() => userStore.user);
const canCreate = computed(() => userStore.canManageUsers);

function canEditTarget(t) {
  if (!me.value) return false;
  if (t.role === ROLE_PLATFORM) return false;            // platform_admin off-limits
  if (me.value.role === ROLE_PLATFORM) return true;       // platform_admin can edit any non-platform
  if (me.value.role === ROLE_TENANT_SUPER) {
    if (t.tenant_id !== me.value.tenant_id) return false;
    if (t.role === ROLE_TENANT_SUPER && t.id !== me.value.id) return false;
    return true;                                          // includes self (password/display)
  }
  if (me.value.role === ROLE_TENANT_ADMIN) {
    // Plain admin can only edit 普通用户 in own tenant, not even themselves.
    return t.tenant_id === me.value.tenant_id
      && t.role === ROLE_TENANT_USER
      && t.id !== me.value.id;
  }
  return false;
}
function canDeleteTarget(t) {
  if (!me.value) return false;
  if (t.id === me.value.id) return false;
  if (t.role === ROLE_PLATFORM) return false;
  if (me.value.role === ROLE_PLATFORM) return true;
  if (me.value.role === ROLE_TENANT_SUPER) {
    return t.tenant_id === me.value.tenant_id && t.role !== ROLE_TENANT_SUPER;
  }
  return false;
}
// Whether the actor can change role/scope on this target (subset of edit).
function canEditPrivileged(t) {
  if (!me.value) return false;
  if (me.value.role === ROLE_PLATFORM) return t.role !== ROLE_PLATFORM;
  if (me.value.role === ROLE_TENANT_SUPER) {
    // Can edit role/scope of admin/user in own tenant; not self (would let
    // them strip their own super status), not other supers.
    return t.tenant_id === me.value.tenant_id
      && t.role !== ROLE_TENANT_SUPER
      && t.id !== me.value.id;
  }
  return false;
}

function roleLabel(role) {
  if (role === ROLE_PLATFORM) return "平台管理员";
  if (role === ROLE_TENANT_SUPER) return "超级管理员";
  if (role === ROLE_TENANT_ADMIN) return "管理员";
  return "普通用户";
}
function roleTagClass(role) {
  if (role === ROLE_PLATFORM) return "tag";
  if (role === ROLE_TENANT_SUPER) return "tag danger";
  if (role === ROLE_TENANT_ADMIN) return "tag success";
  return "tag";
}
function scopeSummary(u) {
  if (u.role === ROLE_PLATFORM || u.role === ROLE_TENANT_SUPER) return "全部数据";
  if (u.data_scope_owners === null || u.data_scope_owners === undefined) return "全部数据";
  if (u.data_scope_owners.length === 0) return "无数据";
  return u.data_scope_owners.join(" / ");
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------
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

async function loadOwners() {
  if (!userStore.canManageUsers) return;
  try {
    const data = await listTenantOwners(targetTenantId.value);
    ownersAvailable.value = data.owners || [];
  } catch (_) { ownersAvailable.value = []; }
}

// ---------------------------------------------------------------------------
// Create / edit dialog
// ---------------------------------------------------------------------------
const dialogOpen = ref(false);
const editing = ref(null);
const form = ref({
  username: "", password: "", role: ROLE_TENANT_USER, display_name: "",
  scope_mode: "all",        // "all" → unrestricted; "selected" → use scope_owners
  scope_owners: [],
});
const formError = ref("");

function openCreate() {
  editing.value = null;
  form.value = {
    username: "", password: "", role: ROLE_TENANT_USER, display_name: "",
    scope_mode: "all", scope_owners: [],
  };
  formError.value = "";
  dialogOpen.value = true;
}
function openEdit(u) {
  editing.value = u;
  const mode = u.data_scope_owners === null || u.data_scope_owners === undefined ? "all" : "selected";
  form.value = {
    username: u.username, password: "", role: u.role, display_name: u.display_name || "",
    scope_mode: mode,
    scope_owners: Array.isArray(u.data_scope_owners) ? u.data_scope_owners.slice() : [],
  };
  formError.value = "";
  dialogOpen.value = true;
}

// Whether the current dialog should expose role/scope controls. Plain admin
// editing a 普通用户 doesn't get these (only password + display_name).
const dialogAllowsPrivileged = computed(() => {
  if (!editing.value) return canCreate.value; // create-mode → super/platform
  return canEditPrivileged(editing.value);
});

function toggleScopeOwner(name) {
  const arr = form.value.scope_owners;
  const i = arr.indexOf(name);
  if (i === -1) arr.push(name); else arr.splice(i, 1);
}

async function submit() {
  formError.value = "";
  try {
    if (editing.value) {
      const body = {};
      if (form.value.password) body.password = form.value.password;
      if (form.value.display_name !== (editing.value.display_name || "")) {
        body.display_name = form.value.display_name;
      }
      if (dialogAllowsPrivileged.value) {
        if (form.value.role !== editing.value.role) body.role = form.value.role;
        // Scope: send when it differs from current. "all" → null; "selected" → list.
        const newScope = form.value.scope_mode === "all" ? null : form.value.scope_owners.slice();
        const oldScope = editing.value.data_scope_owners ?? null;
        if (JSON.stringify(newScope) !== JSON.stringify(oldScope)) {
          body.data_scope_owners = newScope;
        }
      }
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
        data_scope_owners: form.value.scope_mode === "all" ? null : form.value.scope_owners.slice(),
      };
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

function backToTenants() { router.push({ name: "tenants" }); }

onMounted(async () => { await refresh(); await loadCfg(); await loadOwners(); });
watch(() => route.query.tenant_id, async () => { await refresh(); await loadOwners(); });
</script>

<template>
  <section v-if="showCfg" class="panel" style="margin-bottom:16px">
    <header class="panel-head">
      <span class="panel-title">企业配置</span>
      <span class="panel-subtitle">仅超级管理员可见 · 影响看板的「公司利润率」计算</span>
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
        当前生效值：{{ (cfg.fixed_profit_rate * 100).toFixed(2).replace(/\.?0+$/, "") }}%。看板上每个用户卡片的开关只控制自己是否减去此值，不影响这里保存的配置。
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
        <button v-if="canCreate" class="btn primary sm" @click="openCreate">+ 新增账号</button>
      </div>
    </header>
    <table class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">账号</th>
          <th style="text-align:left">显示名</th>
          <th style="text-align:left">角色</th>
          <th style="text-align:left">数据范围</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="u in users" :key="u.id">
          <td>{{ u.username }}<span v-if="u.id === userStore.user?.id" class="tag" style="margin-left:8px">我</span></td>
          <td style="text-align:left">{{ u.display_name || '—' }}</td>
          <td style="text-align:left">
            <span :class="roleTagClass(u.role)">{{ roleLabel(u.role) }}</span>
          </td>
          <td style="text-align:left" :class="(u.role === 'tenant_user' || u.role === 'tenant_admin') && u.data_scope_owners !== null && u.data_scope_owners !== undefined ? '' : 't-muted'">
            {{ scopeSummary(u) }}
          </td>
          <td style="text-align:left" class="t-muted">{{ new Date(u.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button class="btn ghost sm" :disabled="!canEditTarget(u)" @click="openEdit(u)">编辑</button>
            <button class="btn ghost sm" :disabled="!canDeleteTarget(u)" @click="remove(u)" style="color:var(--neg)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !users.length">
          <td colspan="6" class="empty-state">暂无用户</td>
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

        <!-- Role + scope only when the actor has privilege to edit them. -->
        <template v-if="dialogAllowsPrivileged">
          <div class="field">
            <label>角色</label>
            <select class="select" v-model="form.role">
              <option value="tenant_user">普通用户</option>
              <option value="tenant_admin">管理员</option>
            </select>
            <div class="t-muted" style="font-size:11px;margin-top:4px">
              管理员有后台权限（只能编辑普通用户），普通用户无后台。
            </div>
          </div>

          <div class="field">
            <label>数据查看范围</label>
            <div class="scope-mode">
              <label class="scope-radio">
                <input type="radio" value="all" v-model="form.scope_mode" />
                全部数据
              </label>
              <label class="scope-radio">
                <input type="radio" value="selected" v-model="form.scope_mode" />
                指定负责人
              </label>
            </div>
            <div v-if="form.scope_mode === 'selected'" class="owner-pick">
              <div v-if="!ownersAvailable.length" class="t-muted" style="font-size:12px">
                当前企业还没有任何负责人数据，请先导入 Excel。
              </div>
              <label v-for="n in ownersAvailable" :key="n" class="owner-chip">
                <input
                  type="checkbox"
                  :checked="form.scope_owners.includes(n)"
                  @change="toggleScopeOwner(n)"
                />
                <span>{{ n }}</span>
              </label>
            </div>
            <div class="t-muted" style="font-size:11px;margin-top:4px">
              管理员和普通用户均可设置数据范围。超级管理员永远拥有全部数据。
            </div>
          </div>
        </template>

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
  width: 480px; max-width: calc(100vw - 32px);
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-pop);
  display: flex; flex-direction: column;
  max-height: calc(100vh - 60px);
}
.modal-head, .modal-foot {
  padding: 14px 18px; display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid var(--divider);
}
.modal-foot { border-bottom: 0; border-top: 1px solid var(--divider); justify-content: flex-end; }
.modal-body { padding: 18px; overflow-y: auto; }
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

.scope-mode { display: flex; gap: 14px; padding: 4px 0; }
.scope-radio {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 500; color: var(--ink-2); cursor: pointer;
}
.scope-radio input { width: auto; padding: 0; }
.owner-pick {
  display: flex; flex-wrap: wrap; gap: 6px;
  padding: 10px; margin-top: 4px;
  border: 1px dashed var(--border); border-radius: 8px;
  max-height: 180px; overflow-y: auto;
}
.owner-chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border); border-radius: 999px;
  font-size: 12px; cursor: pointer;
  user-select: none; background: var(--surface);
}
.owner-chip input { width: auto; padding: 0; margin: 0; }
.owner-chip:has(input:checked) {
  background: var(--accent-soft); border-color: var(--accent);
  color: var(--accent-ink);
}
</style>
