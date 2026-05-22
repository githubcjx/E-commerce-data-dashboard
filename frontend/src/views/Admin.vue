<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  listUsers, createUser, updateUser, deleteUser, listTenantOwners,
} from "../api/users";
import {
  listDepartments, createDepartment, updateDepartment, deleteDepartment, getDepartment,
} from "../api/departments";
import {
  useUserStore, ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN, ROLE_TENANT_USER,
} from "../stores/user";
import { useUiStore } from "../stores/ui";

const userStore = useUserStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

// ---------------------------------------------------------------------------
// Tab switch — 用户管理 / 部门管理
// ---------------------------------------------------------------------------
const activeTab = ref("users");

// ---------------------------------------------------------------------------
// Target tenant
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
// Permission helpers — mirror backend
// ---------------------------------------------------------------------------
const me = computed(() => userStore.user);
const canCreate = computed(() => userStore.canManageUsers);
// Department management: super_admin / platform_admin can create / delete /
// rename / change rate. Plain admin can only reassign members via the user
// edit dialog (not via the department dialog).
const canManageDepartments = computed(() => userStore.canManageUsers);

function canEditTarget(t) {
  if (!me.value) return false;
  if (t.role === ROLE_PLATFORM) return false;
  if (me.value.role === ROLE_PLATFORM) return true;
  if (me.value.role === ROLE_TENANT_SUPER) {
    if (t.tenant_id !== me.value.tenant_id) return false;
    if (t.role === ROLE_TENANT_SUPER && t.id !== me.value.id) return false;
    return true;
  }
  if (me.value.role === ROLE_TENANT_ADMIN) {
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
function canEditPrivileged(t) {
  if (!me.value) return false;
  if (me.value.role === ROLE_PLATFORM) return t.role !== ROLE_PLATFORM;
  if (me.value.role === ROLE_TENANT_SUPER) {
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
// Users + departments data
// ---------------------------------------------------------------------------
const users = ref([]);
const departments = ref([]);
const loading = ref(false);
const ownersAvailable = ref([]);   // 负责人 list — feeds combobox + scope picker

async function refreshUsers() {
  if (userStore.isPlatformAdmin && !targetTenantId.value) {
    users.value = [];
    return;
  }
  loading.value = true;
  try { users.value = await listUsers(targetTenantId.value); }
  catch (e) { ui.showToast(e.message || "加载失败", "error"); }
  finally { loading.value = false; }
}

async function refreshDepartments() {
  if (userStore.isPlatformAdmin && !targetTenantId.value) {
    departments.value = [];
    return;
  }
  try { departments.value = await listDepartments(targetTenantId.value); }
  catch (e) { ui.showToast(e.message || "部门列表加载失败", "error"); }
}

async function loadOwners() {
  if (!userStore.canManageUsers) return;
  try {
    const data = await listTenantOwners(targetTenantId.value);
    ownersAvailable.value = data.owners || [];
  } catch (_) { ownersAvailable.value = []; }
}

function deptLabel(deptId) {
  if (!deptId) return "—";
  const d = departments.value.find((x) => x.id === deptId);
  return d ? d.name : "—";
}

// ---------------------------------------------------------------------------
// User create / edit dialog
// ---------------------------------------------------------------------------
const dialogOpen = ref(false);
const editing = ref(null);
const form = ref({
  username: "", password: "", role: ROLE_TENANT_USER, display_name: "",
  department_id: null,
  scope_mode: "all",
  scope_owners: [],
});
const formError = ref("");
const usernameErr = ref("");
const passwordErr = ref("");
const departmentErr = ref("");

// Combobox state for display_name / 负责人 picker.
const ownerComboOpen = ref(false);
const ownerComboQuery = ref("");
const ownerComboFiltered = computed(() => {
  const q = (ownerComboQuery.value || "").trim().toLowerCase();
  if (!q) return ownersAvailable.value.slice(0, 50);
  return ownersAvailable.value.filter((n) => n.toLowerCase().includes(q)).slice(0, 50);
});

function resetErrors() {
  formError.value = "";
  usernameErr.value = "";
  passwordErr.value = "";
  departmentErr.value = "";
}

function openCreate() {
  editing.value = null;
  form.value = {
    username: "", password: "", role: ROLE_TENANT_USER, display_name: "",
    department_id: departments.value[0]?.id || null,
    scope_mode: "all", scope_owners: [],
  };
  resetErrors();
  ownerComboOpen.value = false;
  ownerComboQuery.value = "";
  dialogOpen.value = true;
}
function openEdit(u) {
  editing.value = u;
  const mode = u.data_scope_owners === null || u.data_scope_owners === undefined ? "all" : "selected";
  form.value = {
    username: u.username, password: "", role: u.role, display_name: u.display_name || "",
    department_id: u.department_id || null,
    scope_mode: mode,
    scope_owners: Array.isArray(u.data_scope_owners) ? u.data_scope_owners.slice() : [],
  };
  resetErrors();
  ownerComboOpen.value = false;
  ownerComboQuery.value = "";
  dialogOpen.value = true;
}

const dialogAllowsPrivileged = computed(() => {
  if (!editing.value) return canCreate.value;
  return canEditPrivileged(editing.value);
});

// When creating (or editing a non-super), department must be picked. Super
// admins editing themselves don't even see the department row, so the check
// only applies when the row is visible.
const departmentRequired = computed(() => {
  if (!dialogOpen.value) return false;
  if (!editing.value) {
    // create-mode: required for assignable roles (tenant_user / tenant_admin)
    return form.value.role === ROLE_TENANT_USER || form.value.role === ROLE_TENANT_ADMIN;
  }
  return editing.value.role === ROLE_TENANT_USER || editing.value.role === ROLE_TENANT_ADMIN;
});

function toggleScopeOwner(name) {
  const arr = form.value.scope_owners;
  const i = arr.indexOf(name);
  if (i === -1) arr.push(name); else arr.splice(i, 1);
}

// Pick a 负责人 from the combobox. Auto-fills data_scope_owners with just
// that name (one-shot convenience — the user can keep editing the scope
// list afterwards).
function pickOwner(name) {
  form.value.display_name = name;
  ownerComboQuery.value = name;
  ownerComboOpen.value = false;
  if (!editing.value) {
    form.value.scope_mode = "selected";
    form.value.scope_owners = [name];
  }
}

const USERNAME_MIN = 2, USERNAME_MAX = 64;
const PASSWORD_MIN = 6, PASSWORD_MAX = 128;

function validateForCreate() {
  let ok = true;
  const u = (form.value.username || "").trim();
  const p = form.value.password || "";
  form.value.username = u;
  if (!u) { usernameErr.value = "账号不能为空"; ok = false; }
  else if (u.length < USERNAME_MIN) { usernameErr.value = `账号至少 ${USERNAME_MIN} 个字符`; ok = false; }
  else if (u.length > USERNAME_MAX) { usernameErr.value = `账号不能超过 ${USERNAME_MAX} 个字符`; ok = false; }
  if (!p) { passwordErr.value = "密码不能为空"; ok = false; }
  else if (p.length < PASSWORD_MIN) { passwordErr.value = `密码至少 ${PASSWORD_MIN} 位`; ok = false; }
  else if (p.length > PASSWORD_MAX) { passwordErr.value = `密码不能超过 ${PASSWORD_MAX} 个字符`; ok = false; }
  if (departmentRequired.value && !form.value.department_id) {
    departmentErr.value = "请选择部门"; ok = false;
  }
  return ok;
}

function validateForEdit() {
  let ok = true;
  const p = form.value.password || "";
  if (p && (p.length < PASSWORD_MIN || p.length > PASSWORD_MAX)) {
    passwordErr.value = `密码至少 ${PASSWORD_MIN} 位，最多 ${PASSWORD_MAX} 位`;
    ok = false;
  }
  if (departmentRequired.value && !form.value.department_id) {
    departmentErr.value = "请选择部门"; ok = false;
  }
  return ok;
}

async function submit() {
  resetErrors();
  if (editing.value) {
    if (!validateForEdit()) return;
  } else {
    if (!validateForCreate()) return;
  }

  try {
    if (editing.value) {
      const body = {};
      if (form.value.password) body.password = form.value.password;
      if (form.value.display_name !== (editing.value.display_name || "")) {
        body.display_name = form.value.display_name;
      }
      if (dialogAllowsPrivileged.value) {
        if (form.value.role !== editing.value.role) body.role = form.value.role;
        const newScope = form.value.scope_mode === "all" ? null : form.value.scope_owners.slice();
        const oldScope = editing.value.data_scope_owners ?? null;
        if (JSON.stringify(newScope) !== JSON.stringify(oldScope)) {
          body.data_scope_owners = newScope;
        }
      }
      // Department transfer — both super and plain admin can do this when
      // the dialog allowed editing of this target at all.
      if (departmentRequired.value && form.value.department_id !== editing.value.department_id) {
        body.department_id = form.value.department_id;
      }
      await updateUser(editing.value.id, body);
      ui.showToast("已更新", "success");
    } else {
      const body = {
        username: form.value.username,
        password: form.value.password,
        role: form.value.role,
        display_name: form.value.display_name || null,
        department_id: form.value.department_id,
        data_scope_owners: form.value.scope_mode === "all" ? null : form.value.scope_owners.slice(),
      };
      if (userStore.isPlatformAdmin) body.tenant_id = targetTenantId.value;
      await createUser(body);
      ui.showToast("已新增", "success");
    }
    dialogOpen.value = false;
    await refreshUsers();
    await refreshDepartments(); // member counts may have changed
  } catch (e) {
    formError.value = e.message || "保存失败";
  }
}

async function remove(u) {
  if (!confirm(`确认删除账号「${u.username}」？该用户的导入批次将保留（记录归零）。`)) return;
  try {
    await deleteUser(u.id);
    ui.showToast("已删除", "success");
    await refreshUsers();
    await refreshDepartments();
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

// ---------------------------------------------------------------------------
// Department create / edit dialog
// ---------------------------------------------------------------------------
const deptDialogOpen = ref(false);
const editingDept = ref(null);
const deptForm = ref({
  name: "",
  rate_pct: "13",   // string for the input; converted to decimal on submit
  member_ids: [],   // user ids currently checked
});
const deptFormError = ref("");
const deptNameErr = ref("");
const deptRateErr = ref("");

// Users assignable to a department: anyone in this tenant whose role is
// tenant_admin or tenant_user (super_admin is excluded by spec).
const assignableUsers = computed(() => users.value.filter(
  (u) => u.role === ROLE_TENANT_ADMIN || u.role === ROLE_TENANT_USER,
));

function resetDeptErrors() {
  deptFormError.value = "";
  deptNameErr.value = "";
  deptRateErr.value = "";
}

function openDeptCreate() {
  editingDept.value = null;
  deptForm.value = { name: "", rate_pct: "13", member_ids: [] };
  resetDeptErrors();
  deptDialogOpen.value = true;
}

async function openDeptEdit(d) {
  editingDept.value = d;
  deptForm.value = {
    name: d.name,
    rate_pct: (Number(d.fixed_profit_rate) * 100).toFixed(2).replace(/\.?0+$/, ""),
    member_ids: [],
  };
  resetDeptErrors();
  // Fetch detail to get current member list (the list view returns counts only).
  try {
    const detail = await getDepartment(d.id);
    deptForm.value.member_ids = (detail.members || []).map((m) => m.id);
  } catch (_) { /* keep empty */ }
  deptDialogOpen.value = true;
}

function toggleDeptMember(uid) {
  const arr = deptForm.value.member_ids;
  const i = arr.indexOf(uid);
  if (i === -1) arr.push(uid); else arr.splice(i, 1);
}

function validateDeptForm() {
  let ok = true;
  const name = (deptForm.value.name || "").trim();
  deptForm.value.name = name;
  if (!name) { deptNameErr.value = "部门名称不能为空"; ok = false; }
  else if (name.length > 100) { deptNameErr.value = "部门名称不能超过 100 个字符"; ok = false; }
  const pct = Number(deptForm.value.rate_pct);
  if (!Number.isFinite(pct)) { deptRateErr.value = "请输入数字"; ok = false; }
  else if (pct < 0 || pct >= 100) { deptRateErr.value = "请输入 0–99.99 之间的数字"; ok = false; }
  return ok;
}

async function submitDept() {
  resetDeptErrors();
  if (!validateDeptForm()) return;

  const rate = Number(deptForm.value.rate_pct) / 100;
  try {
    if (editingDept.value) {
      const body = {};
      if (deptForm.value.name !== editingDept.value.name) body.name = deptForm.value.name;
      const oldRate = Number(editingDept.value.fixed_profit_rate);
      if (Math.abs(rate - oldRate) > 1e-9) body.fixed_profit_rate = rate;
      body.member_ids = deptForm.value.member_ids.slice();
      await updateDepartment(editingDept.value.id, body);
      ui.showToast("已更新部门", "success");
    } else {
      const body = {
        name: deptForm.value.name,
        fixed_profit_rate: rate,
        member_ids: deptForm.value.member_ids.slice(),
      };
      if (userStore.isPlatformAdmin) body.tenant_id = targetTenantId.value;
      await createDepartment(body);
      ui.showToast("已新增部门", "success");
    }
    deptDialogOpen.value = false;
    await refreshDepartments();
    await refreshUsers();
  } catch (e) {
    deptFormError.value = e.message || "保存失败";
  }
}

async function removeDept(d) {
  if (d.member_count > 0) {
    ui.showToast(`部门下还有 ${d.member_count} 位成员，请先迁出后再删除`, "error");
    return;
  }
  if (!confirm(`确认删除部门「${d.name}」？`)) return;
  try {
    await deleteDepartment(d.id);
    ui.showToast("已删除", "success");
    await refreshDepartments();
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

function backToTenants() { router.push({ name: "tenants" }); }

onMounted(async () => {
  await Promise.all([refreshDepartments(), refreshUsers(), loadOwners()]);
});
watch(() => route.query.tenant_id, async () => {
  await Promise.all([refreshDepartments(), refreshUsers(), loadOwners()]);
});
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <div class="tabs-wrap">
        <button
          :class="['tab-pill', { 'is-active': activeTab === 'users' }]"
          @click="activeTab = 'users'"
        >用户管理</button>
        <button
          :class="['tab-pill', { 'is-active': activeTab === 'departments' }]"
          @click="activeTab = 'departments'"
        >部门管理</button>
      </div>
      <span class="panel-subtitle" v-if="targetTenantLabel">{{ targetTenantLabel }}</span>
      <div class="panel-actions">
        <button v-if="userStore.isPlatformAdmin" class="btn ghost sm" @click="backToTenants">← 返回企业列表</button>
        <button
          v-if="activeTab === 'users' && canCreate"
          class="btn primary sm" @click="openCreate"
        >+ 新增账号</button>
        <button
          v-if="activeTab === 'departments' && canManageDepartments"
          class="btn primary sm" @click="openDeptCreate"
        >+ 新增部门</button>
      </div>
    </header>

    <!-- ======================= USERS TAB ======================= -->
    <table v-if="activeTab === 'users'" class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">账号</th>
          <th style="text-align:left">显示名 / 负责人</th>
          <th style="text-align:left">角色</th>
          <th style="text-align:left">部门</th>
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
          <td style="text-align:left" :class="u.department_name ? '' : 't-muted'">
            {{ u.department_name || '—' }}
          </td>
          <td style="text-align:left" :class="(u.role === 'tenant_user' || u.role === 'tenant_admin') && u.data_scope_owners !== null && u.data_scope_owners !== undefined ? '' : 't-muted'">
            {{ scopeSummary(u) }}
          </td>
          <td style="text-align:left" class="t-muted">{{ new Date(u.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button v-if="canEditTarget(u)" class="btn ghost sm" @click="openEdit(u)">编辑</button>
            <button v-if="canDeleteTarget(u)" class="btn ghost sm" @click="remove(u)" style="color:var(--neg)">删除</button>
            <span v-if="!canEditTarget(u) && !canDeleteTarget(u)" class="t-muted" style="font-size:12px">—</span>
          </td>
        </tr>
        <tr v-if="!loading && !users.length">
          <td colspan="7" class="empty-state">暂无用户</td>
        </tr>
      </tbody>
    </table>

    <!-- ===================== DEPARTMENTS TAB =================== -->
    <table v-else class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">部门名称</th>
          <th style="text-align:left">固定利润率</th>
          <th style="text-align:left">成员</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in departments" :key="d.id">
          <td style="text-align:left">{{ d.name }}</td>
          <td style="text-align:left" class="mono">{{ (Number(d.fixed_profit_rate) * 100).toFixed(2).replace(/\.?0+$/, "") }}%</td>
          <td style="text-align:left">{{ d.member_count }} 人</td>
          <td style="text-align:left" class="t-muted">{{ new Date(d.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button v-if="canManageDepartments" class="btn ghost sm" @click="openDeptEdit(d)">编辑</button>
            <button
              v-if="canManageDepartments"
              class="btn ghost sm"
              @click="removeDept(d)"
              style="color:var(--neg)"
              :title="d.member_count > 0 ? '请先迁出成员后再删除' : ''"
            >删除</button>
            <span v-if="!canManageDepartments" class="t-muted" style="font-size:12px">—</span>
          </td>
        </tr>
        <tr v-if="!departments.length">
          <td colspan="5" class="empty-state">暂无部门，请先「新增部门」</td>
        </tr>
      </tbody>
    </table>
  </section>

  <!-- =================== USER DIALOG =================== -->
  <div v-if="dialogOpen" class="modal-backdrop" @click.self="dialogOpen = false">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editing ? "编辑账号" : "新增账号" }}</span>
        <button class="btn ghost sm" @click="dialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field" :class="{ 'has-error': usernameErr }">
          <label>
            账号
            <span v-if="!editing" class="req-mark" title="必填">*</span>
          </label>
          <input
            :disabled="!!editing"
            v-model="form.username"
            placeholder="至少 2 个字符"
            autocomplete="off"
            @input="usernameErr = ''"
          />
          <div v-if="usernameErr" class="field-error">{{ usernameErr }}</div>
        </div>
        <div class="field" :class="{ 'has-error': passwordErr }">
          <label>
            密码
            <span v-if="!editing" class="req-mark" title="必填">*</span>
            <span v-if="editing" class="t-muted" style="font-size:11px">（留空则不修改）</span>
          </label>
          <input
            type="password"
            v-model="form.password"
            placeholder="至少 6 位"
            autocomplete="new-password"
            @input="passwordErr = ''"
          />
          <div v-if="passwordErr" class="field-error">{{ passwordErr }}</div>
        </div>

        <!-- 显示名 / 负责人 combobox. Free-text input + dropdown that filters
             the tenant's known 负责人 list. Picking from the dropdown auto-
             fills the data-scope below. -->
        <div class="field">
          <label>
            显示名 / 负责人
            <span class="t-muted" style="font-size:11px">（可从下拉选择已有负责人，也可输入新名）</span>
          </label>
          <div class="combobox" @click.stop>
            <input
              v-model="form.display_name"
              placeholder="选择或输入负责人姓名"
              autocomplete="off"
              @focus="ownerComboOpen = true; ownerComboQuery = form.display_name"
              @input="ownerComboQuery = form.display_name; ownerComboOpen = true"
            />
            <div v-if="ownerComboOpen && ownerComboFiltered.length" class="combo-pop">
              <button
                v-for="n in ownerComboFiltered"
                :key="n" type="button" class="combo-item"
                @click.stop="pickOwner(n)"
              >{{ n }}</button>
            </div>
          </div>
        </div>

        <!-- Department — required for tenant_admin / tenant_user -->
        <div
          v-if="departmentRequired"
          class="field"
          :class="{ 'has-error': departmentErr }"
        >
          <label>
            所属部门
            <span class="req-mark" title="必填">*</span>
          </label>
          <select class="select" v-model.number="form.department_id" @change="departmentErr = ''">
            <option :value="null" disabled>请选择部门</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">
              {{ d.name }} · {{ (Number(d.fixed_profit_rate) * 100).toFixed(2).replace(/\.?0+$/, "") }}%
            </option>
          </select>
          <div v-if="departmentErr" class="field-error">{{ departmentErr }}</div>
          <div v-if="!departments.length" class="t-muted" style="font-size:11px;margin-top:4px">
            当前企业暂无部门，请先到「部门管理」新增。
          </div>
        </div>

        <!-- Role + scope only when actor can change them. Plain admin
             editing a 普通用户 sees neither. -->
        <template v-if="dialogAllowsPrivileged">
          <div class="field">
            <label>角色</label>
            <select class="select" v-model="form.role">
              <option value="tenant_user">普通用户</option>
              <option value="tenant_admin">管理员</option>
            </select>
            <div class="t-muted" style="font-size:11px;margin-top:4px">
              管理员有后台权限（只能编辑普通用户、调整部门成员），普通用户无后台。
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
              选择负责人时已自动勾选；可继续添加其他负责人。超级管理员永远拥有全部数据。
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

  <!-- =================== DEPARTMENT DIALOG =================== -->
  <div v-if="deptDialogOpen" class="modal-backdrop" @click.self="deptDialogOpen = false">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editingDept ? "编辑部门" : "新增部门" }}</span>
        <button class="btn ghost sm" @click="deptDialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field" :class="{ 'has-error': deptNameErr }">
          <label>
            部门名称
            <span class="req-mark" title="必填">*</span>
          </label>
          <input
            v-model="deptForm.name"
            placeholder="例如：销售一部"
            @input="deptNameErr = ''"
          />
          <div v-if="deptNameErr" class="field-error">{{ deptNameErr }}</div>
        </div>

        <div class="field" :class="{ 'has-error': deptRateErr }">
          <label>
            固定利润率
            <span class="req-mark" title="必填">*</span>
            <span class="t-muted" style="font-size:11px">公司利润率 = 经营利润率 − 此值</span>
          </label>
          <div class="cfg-input">
            <input
              type="number" min="0" max="99.99" step="0.01"
              v-model="deptForm.rate_pct"
              @input="deptRateErr = ''"
            />
            <span class="suffix">%</span>
          </div>
          <div v-if="deptRateErr" class="field-error">{{ deptRateErr }}</div>
        </div>

        <div class="field">
          <label>
            成员
            <span class="t-muted" style="font-size:11px">（多选，超级管理员不可加入部门）</span>
          </label>
          <div class="owner-pick" style="max-height:240px">
            <div v-if="!assignableUsers.length" class="t-muted" style="font-size:12px">
              当前企业暂无可分配成员（先去新增普通用户/管理员账号）。
            </div>
            <label v-for="u in assignableUsers" :key="u.id" class="owner-chip">
              <input
                type="checkbox"
                :checked="deptForm.member_ids.includes(u.id)"
                @change="toggleDeptMember(u.id)"
              />
              <span>
                {{ u.username }}
                <span v-if="u.display_name" class="t-muted">· {{ u.display_name }}</span>
                <span
                  v-if="u.department_id && (!editingDept || u.department_id !== editingDept.id)"
                  class="dept-from"
                >← {{ deptLabel(u.department_id) }}</span>
              </span>
            </label>
          </div>
          <div class="t-muted" style="font-size:11px;margin-top:4px">
            勾选会将成员加入此部门（自动从原部门移出）；取消勾选则把成员移出部门（不会自动加到别处）。
          </div>
        </div>

        <div class="error">{{ deptFormError }}</div>
      </div>
      <footer class="modal-foot">
        <button class="btn" @click="deptDialogOpen = false">取消</button>
        <button class="btn primary" @click="submitDept">保存</button>
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
  transition: border-color 0.15s, box-shadow 0.15s;
}
.field input:focus, .field select:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-line); }
.field input:disabled { background: var(--bg-elev); color: var(--ink-4); cursor: not-allowed; }

.req-mark { color: var(--neg); font-weight: 600; margin-left: 2px; }
.field-error { font-size: 12px; color: var(--neg); font-family: var(--font-sans); }
.field.has-error input,
.field.has-error select {
  border-color: var(--neg);
  box-shadow: 0 0 0 3px oklch(56% 0.16 30 / 0.12);
}

.modal-backdrop {
  position: fixed; inset: 0; background: rgba(20, 20, 15, 0.45);
  display: grid; place-items: center; z-index: 80; backdrop-filter: blur(4px);
}
.modal-card {
  width: 520px; max-width: calc(100vw - 32px);
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

.cfg-input { display: flex; align-items: center; gap: 6px; }
.cfg-input input {
  width: 120px; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  font-family: var(--font-mono); font-size: 14px; color: var(--ink);
  background: var(--surface);
}
.cfg-input input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-line); }
.cfg-input .suffix { color: var(--ink-4); font-family: var(--font-mono); font-size: 13px; }

/* Tab pills in the panel header */
.tabs-wrap { display: inline-flex; gap: 4px; padding: 4px; background: var(--bg-elev);
  border-radius: 10px; }
.tab-pill {
  appearance: none; border: 0; background: transparent; color: var(--ink-3);
  padding: 6px 14px; font: inherit; font-size: 13px; font-weight: 500;
  border-radius: 7px; cursor: pointer; transition: background .15s, color .15s;
}
.tab-pill:hover { color: var(--ink); }
.tab-pill.is-active { background: var(--surface); color: var(--ink); box-shadow: var(--shadow-card); }

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
.dept-from { color: var(--ink-4); font-size: 11px; margin-left: 4px; }

/* Combobox */
.combobox { position: relative; }
.combo-pop {
  position: absolute; left: 0; right: 0; top: calc(100% + 4px); z-index: 5;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: var(--shadow-pop); max-height: 220px; overflow-y: auto; padding: 4px;
}
.combo-item {
  appearance: none; border: 0; background: transparent; width: 100%;
  text-align: left; padding: 7px 10px; border-radius: 6px;
  font: inherit; font-size: 13px; color: var(--ink); cursor: pointer;
}
.combo-item:hover { background: var(--surface-hover); }
</style>
