<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  listUsers, createUser, updateUser, deleteUser, listTenantOwners,
} from "../api/users";
import {
  listDepartments, createDepartment, updateDepartment, deleteDepartment,
} from "../api/departments";
import { listShops, applyShopFeeBatch } from "../api/shops";
import {
  useUserStore, ROLE_PLATFORM, ROLE_TENANT_SUPER, ROLE_TENANT_ADMIN, ROLE_TENANT_USER,
} from "../stores/user";
import { useUiStore } from "../stores/ui";

const userStore = useUserStore();
const ui = useUiStore();
const route = useRoute();
const router = useRouter();

// Tab switch: 用户管理 / 部门管理 / 店铺管理
const activeTab = ref("users");

// ---------------------------------------------------------------------------
// Target tenant resolution (unchanged from before)
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
// Permission helpers
// ---------------------------------------------------------------------------
const me = computed(() => userStore.user);
const canCreate = computed(() => userStore.canManageUsers);
const canManageDepartments = computed(() => userStore.canManageUsers);
const canManageShops = computed(() => userStore.canManageUsers);

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

// Render "前 N + N" for long member/shop lists in the department row.
function previewList(items, getLabel, n = 3) {
  if (!items || !items.length) return { shown: [], more: 0 };
  const labels = items.map(getLabel);
  return { shown: labels.slice(0, n), more: Math.max(0, labels.length - n) };
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------
const users = ref([]);
const departments = ref([]);
const shops = ref([]);
const loading = ref(false);
const ownersAvailable = ref([]);

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
  catch (e) { ui.showToast(e.message || "部门加载失败", "error"); }
}

async function refreshShops() {
  if (userStore.isPlatformAdmin && !targetTenantId.value) {
    shops.value = [];
    return;
  }
  try { shops.value = await listShops(targetTenantId.value); }
  catch (e) { ui.showToast(e.message || "店铺加载失败", "error"); }
}

async function loadOwners() {
  if (!userStore.canManageUsers) return;
  try {
    const data = await listTenantOwners(targetTenantId.value);
    ownersAvailable.value = data.owners || [];
  } catch (_) { ownersAvailable.value = []; }
}

// ---------------------------------------------------------------------------
// User dialog
// ---------------------------------------------------------------------------
const dialogOpen = ref(false);
const editing = ref(null);
const form = ref({
  username: "", password: "", role: ROLE_TENANT_USER, display_name: "",
  department_ids: [],
  scope_mode: "all",
  scope_owners: [],
});
const formError = ref("");
const usernameErr = ref("");
const passwordErr = ref("");
const departmentErr = ref("");

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
    department_ids: departments.value[0] ? [departments.value[0].id] : [],
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
    department_ids: (u.departments || []).map((d) => d.id),
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

const departmentRequired = computed(() => {
  if (!dialogOpen.value) return false;
  if (!editing.value) {
    return form.value.role === ROLE_TENANT_USER || form.value.role === ROLE_TENANT_ADMIN;
  }
  return editing.value.role === ROLE_TENANT_USER || editing.value.role === ROLE_TENANT_ADMIN;
});

function toggleScopeOwner(name) {
  const arr = form.value.scope_owners;
  const i = arr.indexOf(name);
  if (i === -1) arr.push(name); else arr.splice(i, 1);
}

function toggleDeptId(id) {
  const arr = form.value.department_ids;
  const i = arr.indexOf(id);
  if (i === -1) arr.push(id); else arr.splice(i, 1);
  departmentErr.value = "";
}

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
  if (departmentRequired.value && !form.value.department_ids.length) {
    departmentErr.value = "请至少选择一个部门"; ok = false;
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
  if (departmentRequired.value && !form.value.department_ids.length) {
    departmentErr.value = "请至少选择一个部门"; ok = false;
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
      // Department membership — send when differing.
      const newDepts = form.value.department_ids.slice().sort();
      const oldDepts = (editing.value.departments || []).map((d) => d.id).sort();
      if (JSON.stringify(newDepts) !== JSON.stringify(oldDepts)) {
        body.department_ids = newDepts;
      }
      await updateUser(editing.value.id, body);
      ui.showToast("已更新", "success");
    } else {
      const body = {
        username: form.value.username,
        password: form.value.password,
        role: form.value.role,
        display_name: form.value.display_name || null,
        department_ids: form.value.department_ids.slice(),
        data_scope_owners: form.value.scope_mode === "all" ? null : form.value.scope_owners.slice(),
      };
      if (userStore.isPlatformAdmin) body.tenant_id = targetTenantId.value;
      await createUser(body);
      ui.showToast("已新增", "success");
    }
    dialogOpen.value = false;
    await Promise.all([refreshUsers(), refreshDepartments()]);
  } catch (e) {
    formError.value = e.message || "保存失败";
  }
}

async function remove(u) {
  if (!confirm(`确认删除账号「${u.username}」？该用户的导入批次将保留（记录归零）。`)) return;
  try {
    await deleteUser(u.id);
    ui.showToast("已删除", "success");
    await Promise.all([refreshUsers(), refreshDepartments()]);
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

// ---------------------------------------------------------------------------
// Department dialog
// ---------------------------------------------------------------------------
const deptDialogOpen = ref(false);
const editingDept = ref(null);
const deptForm = ref({
  name: "",
  member_ids: [],
  view_shop_codes: [],
});
const deptFormError = ref("");
const deptNameErr = ref("");

const assignableUsers = computed(() => users.value.filter(
  (u) => u.role === ROLE_TENANT_ADMIN || u.role === ROLE_TENANT_USER,
));

function resetDeptErrors() {
  deptFormError.value = "";
  deptNameErr.value = "";
}

function openDeptCreate() {
  editingDept.value = null;
  deptForm.value = { name: "", member_ids: [], view_shop_codes: [] };
  resetDeptErrors();
  deptDialogOpen.value = true;
}

function openDeptEdit(d) {
  editingDept.value = d;
  deptForm.value = {
    name: d.name,
    member_ids: (d.members || []).map((m) => m.id),
    view_shop_codes: (d.view_shops || []).map((s) => s.shop_code),
  };
  resetDeptErrors();
  deptDialogOpen.value = true;
}

function toggleDeptMember(uid) {
  const arr = deptForm.value.member_ids;
  const i = arr.indexOf(uid);
  if (i === -1) arr.push(uid); else arr.splice(i, 1);
}
function toggleDeptShop(code) {
  const arr = deptForm.value.view_shop_codes;
  const i = arr.indexOf(code);
  if (i === -1) arr.push(code); else arr.splice(i, 1);
}

// Which other department currently owns this shop's view (for the picker
// hint)? Returns null if it's free or already in this department.
function shopCurrentViewDept(shopCode) {
  if (!shopCode) return null;
  for (const d of departments.value) {
    if (editingDept.value && d.id === editingDept.value.id) continue;
    if ((d.view_shops || []).some((s) => s.shop_code === shopCode)) return d;
  }
  return null;
}

function validateDeptForm() {
  let ok = true;
  const name = (deptForm.value.name || "").trim();
  deptForm.value.name = name;
  if (!name) { deptNameErr.value = "部门名称不能为空"; ok = false; }
  else if (name.length > 100) { deptNameErr.value = "部门名称不能超过 100 个字符"; ok = false; }
  return ok;
}

async function submitDept() {
  resetDeptErrors();
  if (!validateDeptForm()) return;

  try {
    if (editingDept.value) {
      const body = {};
      if (deptForm.value.name !== editingDept.value.name) body.name = deptForm.value.name;
      body.member_ids = deptForm.value.member_ids.slice();
      body.view_shop_codes = deptForm.value.view_shop_codes.slice();
      await updateDepartment(editingDept.value.id, body);
      ui.showToast("已更新部门", "success");
    } else {
      const body = {
        name: deptForm.value.name,
        member_ids: deptForm.value.member_ids.slice(),
        view_shop_codes: deptForm.value.view_shop_codes.slice(),
      };
      if (userStore.isPlatformAdmin) body.tenant_id = targetTenantId.value;
      await createDepartment(body);
      ui.showToast("已新增部门", "success");
    }
    deptDialogOpen.value = false;
    await Promise.all([refreshDepartments(), refreshUsers(), refreshShops()]);
  } catch (e) {
    deptFormError.value = e.message || "保存失败";
  }
}

async function removeDept(d) {
  if ((d.members || []).length > 0) {
    ui.showToast(`部门下还有 ${d.members.length} 位成员，请先迁出后再删除`, "error");
    return;
  }
  if (!confirm(`确认删除部门「${d.name}」？`)) return;
  try {
    await deleteDepartment(d.id);
    ui.showToast("已删除", "success");
    await Promise.all([refreshDepartments(), refreshShops()]);
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

// ---------------------------------------------------------------------------
// Shops dialog
// ---------------------------------------------------------------------------
const shopDialogOpen = ref(false);
const editingShop = ref(null); // null = create-new, otherwise pre-populate
const shopForm = ref({
  fee_department_id: null,
  per_capita_share: "0",
  ship_service_tax_rate_pct: "0", // pct, converted to fraction on save
  shop_codes: [],
});
const shopFormError = ref("");
const shopFeeDeptErr = ref("");
const shopShareErr = ref("");
const shopTaxErr = ref("");

function resetShopErrors() {
  shopFormError.value = "";
  shopFeeDeptErr.value = "";
  shopShareErr.value = "";
  shopTaxErr.value = "";
}

function openShopCreate() {
  // "New" = a fresh fee config to apply to N shops.
  editingShop.value = null;
  shopForm.value = {
    fee_department_id: departments.value[0]?.id || null,
    per_capita_share: "0",
    ship_service_tax_rate_pct: "0",
    shop_codes: [],
  };
  resetShopErrors();
  shopDialogOpen.value = true;
}

function openShopEdit(shop) {
  // Pre-populate from one shop's current config; the multi-select starts
  // with just that shop, but the admin can extend to apply this same
  // config to additional shops.
  editingShop.value = shop;
  shopForm.value = {
    fee_department_id: shop.fee_department_id,
    per_capita_share: String(Number(shop.per_capita_share || 0)),
    ship_service_tax_rate_pct: (Number(shop.ship_service_tax_rate || 0) * 100).toFixed(2).replace(/\.?0+$/, ""),
    shop_codes: [shop.shop_code],
  };
  resetShopErrors();
  shopDialogOpen.value = true;
}

function toggleShopFormCode(code) {
  const arr = shopForm.value.shop_codes;
  const i = arr.indexOf(code);
  if (i === -1) arr.push(code); else arr.splice(i, 1);
}

// Which fee-department currently owns this shop (for the picker hint)?
function shopCurrentFeeDept(shopCode) {
  if (!shopCode) return null;
  const s = shops.value.find((x) => x.shop_code === shopCode);
  if (!s || !s.fee_department_id) return null;
  if (editingShop.value && s.fee_department_id === shopForm.value.fee_department_id) return null;
  return { id: s.fee_department_id, name: s.fee_department_name };
}

function validateShopForm() {
  let ok = true;
  if (!shopForm.value.fee_department_id) { shopFeeDeptErr.value = "请选择费用所属部门"; ok = false; }
  const share = Number(shopForm.value.per_capita_share);
  if (!Number.isFinite(share) || share < 0) { shopShareErr.value = "请输入大于等于 0 的数字"; ok = false; }
  const taxPct = Number(shopForm.value.ship_service_tax_rate_pct);
  if (!Number.isFinite(taxPct) || taxPct < 0 || taxPct >= 100) {
    shopTaxErr.value = "请输入 0–99.99 之间的数字"; ok = false;
  }
  if (!shopForm.value.shop_codes.length) {
    shopFormError.value = "请至少选择一个店铺";
    ok = false;
  }
  return ok;
}

async function submitShop() {
  resetShopErrors();
  if (!validateShopForm()) return;
  const body = {
    fee_department_id: shopForm.value.fee_department_id,
    per_capita_share: Number(shopForm.value.per_capita_share),
    ship_service_tax_rate: Number(shopForm.value.ship_service_tax_rate_pct) / 100,
    shop_codes: shopForm.value.shop_codes.slice(),
  };
  try {
    const r = await applyShopFeeBatch(body, targetTenantId.value);
    ui.showToast(`已更新 ${r.updated} 个店铺的费用配置`, "success");
    shopDialogOpen.value = false;
    await refreshShops();
  } catch (e) {
    shopFormError.value = e.message || "保存失败";
  }
}

function backToTenants() { router.push({ name: "tenants" }); }

onMounted(async () => {
  await Promise.all([refreshDepartments(), refreshUsers(), refreshShops(), loadOwners()]);
});
watch(() => route.query.tenant_id, async () => {
  await Promise.all([refreshDepartments(), refreshUsers(), refreshShops(), loadOwners()]);
});
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <div class="tabs-wrap">
        <button :class="['tab-pill', { 'is-active': activeTab === 'users' }]" @click="activeTab = 'users'">用户管理</button>
        <button :class="['tab-pill', { 'is-active': activeTab === 'departments' }]" @click="activeTab = 'departments'">部门管理</button>
        <button :class="['tab-pill', { 'is-active': activeTab === 'shops' }]" @click="activeTab = 'shops'">店铺管理</button>
      </div>
      <span class="panel-subtitle" v-if="targetTenantLabel">{{ targetTenantLabel }}</span>
      <div class="panel-actions">
        <button v-if="userStore.isPlatformAdmin" class="btn ghost sm" @click="backToTenants">← 返回企业列表</button>
        <button v-if="activeTab === 'users' && canCreate" class="btn primary sm" @click="openCreate">+ 新增账号</button>
        <button v-if="activeTab === 'departments' && canManageDepartments" class="btn primary sm" @click="openDeptCreate">+ 新增部门</button>
        <button v-if="activeTab === 'shops' && canManageShops" class="btn primary sm" @click="openShopCreate">+ 新增费用配置</button>
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
          <td style="text-align:left" :class="(u.departments || []).length ? '' : 't-muted'">
            <template v-if="(u.departments || []).length">{{ u.departments.map((d) => d.name).join(' / ') }}</template>
            <template v-else>—</template>
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
    <table v-else-if="activeTab === 'departments'" class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">部门名称</th>
          <th style="text-align:left">店铺</th>
          <th style="text-align:left">成员</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="d in departments" :key="d.id">
          <td style="text-align:left">{{ d.name }}</td>
          <td style="text-align:left" :class="(d.view_shops || []).length ? '' : 't-muted'">
            <template v-if="(d.view_shops || []).length">
              {{ previewList(d.view_shops, (s) => s.shop_name || s.shop_code).shown.join('、') }}
              <span v-if="previewList(d.view_shops, () => '').more" class="more-tag" :title="d.view_shops.map((s) => s.shop_name || s.shop_code).join('、')">
                +{{ previewList(d.view_shops, () => '').more }}
              </span>
            </template>
            <template v-else>—</template>
          </td>
          <td style="text-align:left" :class="(d.members || []).length ? '' : 't-muted'">
            <template v-if="(d.members || []).length">
              {{ previewList(d.members, (m) => m.display_name || m.username).shown.join('、') }}
              <span v-if="previewList(d.members, () => '').more" class="more-tag" :title="d.members.map((m) => m.display_name || m.username).join('、')">
                +{{ previewList(d.members, () => '').more }}
              </span>
            </template>
            <template v-else>—</template>
          </td>
          <td style="text-align:left" class="t-muted">{{ new Date(d.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button v-if="canManageDepartments" class="btn ghost sm" @click="openDeptEdit(d)">编辑</button>
            <button v-if="canManageDepartments" class="btn ghost sm" @click="removeDept(d)" style="color:var(--neg)">删除</button>
            <span v-if="!canManageDepartments" class="t-muted" style="font-size:12px">—</span>
          </td>
        </tr>
        <tr v-if="!departments.length">
          <td colspan="5" class="empty-state">暂无部门，请先「新增部门」</td>
        </tr>
      </tbody>
    </table>

    <!-- ======================= SHOPS TAB ======================= -->
    <table v-else class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">店铺</th>
          <th style="text-align:left">费用所属部门</th>
          <th style="text-align:left">固定费用（人员均摊）</th>
          <th style="text-align:left">百分比费用（发货客服税费）</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:left">更新时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="s in shops" :key="s.id">
          <td style="text-align:left">{{ s.shop_name || s.shop_code }}<span class="mono t-muted" style="margin-left:6px;font-size:11px">{{ s.shop_code }}</span></td>
          <td style="text-align:left" :class="s.fee_department_name ? '' : 't-muted'">{{ s.fee_department_name || '—' }}</td>
          <td style="text-align:left" class="mono">{{ Number(s.per_capita_share || 0).toLocaleString('en-US') }}</td>
          <td style="text-align:left" class="mono">{{ (Number(s.ship_service_tax_rate || 0) * 100).toFixed(2).replace(/\.?0+$/, '') }}%</td>
          <td style="text-align:left" class="t-muted">{{ new Date(s.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td style="text-align:left" class="t-muted">{{ new Date(s.updated_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button v-if="canManageShops" class="btn ghost sm" @click="openShopEdit(s)">编辑</button>
            <span v-else class="t-muted" style="font-size:12px">—</span>
          </td>
        </tr>
        <tr v-if="!shops.length">
          <td colspan="7" class="empty-state">暂无店铺（导入数据后会自动出现在这里）</td>
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
          <label>账号 <span v-if="!editing" class="req-mark" title="必填">*</span></label>
          <input :disabled="!!editing" v-model="form.username" placeholder="至少 2 个字符" autocomplete="off" @input="usernameErr = ''" />
          <div v-if="usernameErr" class="field-error">{{ usernameErr }}</div>
        </div>
        <div class="field" :class="{ 'has-error': passwordErr }">
          <label>
            密码 <span v-if="!editing" class="req-mark" title="必填">*</span>
            <span v-if="editing" class="t-muted" style="font-size:11px">（留空则不修改）</span>
          </label>
          <input type="password" v-model="form.password" placeholder="至少 6 位" autocomplete="new-password" @input="passwordErr = ''" />
          <div v-if="passwordErr" class="field-error">{{ passwordErr }}</div>
        </div>

        <div class="field">
          <label>
            显示名 / 负责人
            <span class="t-muted" style="font-size:11px">（可下拉选择已有负责人，也可输入新名）</span>
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
              <button v-for="n in ownerComboFiltered" :key="n" type="button" class="combo-item" @click.stop="pickOwner(n)">{{ n }}</button>
            </div>
          </div>
        </div>

        <!-- Departments: multi-select. A user can belong to many. -->
        <div v-if="departmentRequired" class="field" :class="{ 'has-error': departmentErr }">
          <label>
            所属部门 <span class="req-mark" title="必填">*</span>
            <span class="t-muted" style="font-size:11px">（可多选）</span>
          </label>
          <div class="owner-pick">
            <div v-if="!departments.length" class="t-muted" style="font-size:12px">
              当前企业暂无部门，请先到「部门管理」新增。
            </div>
            <label v-for="d in departments" :key="d.id" class="owner-chip">
              <input type="checkbox" :checked="form.department_ids.includes(d.id)" @change="toggleDeptId(d.id)" />
              <span>{{ d.name }}</span>
            </label>
          </div>
          <div v-if="departmentErr" class="field-error">{{ departmentErr }}</div>
        </div>

        <template v-if="dialogAllowsPrivileged">
          <div class="field">
            <label>角色</label>
            <select class="select" v-model="form.role">
              <option value="tenant_user">普通用户</option>
              <option value="tenant_admin">管理员</option>
            </select>
          </div>

          <div class="field">
            <label>数据查看范围</label>
            <div class="scope-mode">
              <label class="scope-radio">
                <input type="radio" value="all" v-model="form.scope_mode" />全部数据
              </label>
              <label class="scope-radio">
                <input type="radio" value="selected" v-model="form.scope_mode" />指定负责人
              </label>
            </div>
            <div v-if="form.scope_mode === 'selected'" class="owner-pick">
              <div v-if="!ownersAvailable.length" class="t-muted" style="font-size:12px">
                当前企业还没有任何负责人数据，请先导入 Excel。
              </div>
              <label v-for="n in ownersAvailable" :key="n" class="owner-chip">
                <input type="checkbox" :checked="form.scope_owners.includes(n)" @change="toggleScopeOwner(n)" />
                <span>{{ n }}</span>
              </label>
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
          <label>部门名称 <span class="req-mark" title="必填">*</span></label>
          <input v-model="deptForm.name" placeholder="例如：销售一部" @input="deptNameErr = ''" />
          <div v-if="deptNameErr" class="field-error">{{ deptNameErr }}</div>
        </div>

        <div class="field">
          <label>
            成员
            <span class="t-muted" style="font-size:11px">（多选，一个用户可属于多个部门；超管不能加入）</span>
          </label>
          <div class="owner-pick" style="max-height:200px">
            <div v-if="!assignableUsers.length" class="t-muted" style="font-size:12px">
              当前企业暂无可分配成员。
            </div>
            <label v-for="u in assignableUsers" :key="u.id" class="owner-chip">
              <input type="checkbox" :checked="deptForm.member_ids.includes(u.id)" @change="toggleDeptMember(u.id)" />
              <span>
                {{ u.username }}
                <span v-if="u.display_name" class="t-muted">· {{ u.display_name }}</span>
              </span>
            </label>
          </div>
        </div>

        <div class="field">
          <label>
            店铺
            <span class="t-muted" style="font-size:11px">（部门视角下展示的店铺；一个店铺只能在一个部门视角下）</span>
          </label>
          <div class="owner-pick" style="max-height:200px">
            <div v-if="!shops.length" class="t-muted" style="font-size:12px">
              暂无店铺，请先导入数据让店铺出现。
            </div>
            <label v-for="s in shops" :key="s.id" class="owner-chip">
              <input type="checkbox" :checked="deptForm.view_shop_codes.includes(s.shop_code)" @change="toggleDeptShop(s.shop_code)" />
              <span>
                {{ s.shop_name || s.shop_code }}
                <span v-if="shopCurrentViewDept(s.shop_code)" class="dept-from">
                  ← {{ shopCurrentViewDept(s.shop_code).name }}
                </span>
              </span>
            </label>
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

  <!-- =================== SHOP FEE DIALOG =================== -->
  <div v-if="shopDialogOpen" class="modal-backdrop" @click.self="shopDialogOpen = false">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editingShop ? "编辑店铺费用配置" : "新增店铺费用配置" }}</span>
        <button class="btn ghost sm" @click="shopDialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field" :class="{ 'has-error': shopFeeDeptErr }">
          <label>费用所属部门 <span class="req-mark" title="必填">*</span></label>
          <select class="select" v-model.number="shopForm.fee_department_id" @change="shopFeeDeptErr = ''">
            <option :value="null" disabled>请选择部门</option>
            <option v-for="d in departments" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
          <div v-if="shopFeeDeptErr" class="field-error">{{ shopFeeDeptErr }}</div>
        </div>

        <div class="field" :class="{ 'has-error': shopShareErr }">
          <label>人员均摊（固定费用） <span class="req-mark" title="必填">*</span></label>
          <div class="cfg-input">
            <input type="number" min="0" step="0.01" v-model="shopForm.per_capita_share" @input="shopShareErr = ''" />
            <span class="suffix">元</span>
          </div>
          <div v-if="shopShareErr" class="field-error">{{ shopShareErr }}</div>
        </div>

        <div class="field" :class="{ 'has-error': shopTaxErr }">
          <label>发货客服税费（百分比费用） <span class="req-mark" title="必填">*</span></label>
          <div class="cfg-input">
            <input type="number" min="0" max="99.99" step="0.01" v-model="shopForm.ship_service_tax_rate_pct" @input="shopTaxErr = ''" />
            <span class="suffix">%</span>
          </div>
          <div v-if="shopTaxErr" class="field-error">{{ shopTaxErr }}</div>
        </div>

        <div class="field">
          <label>
            适用店铺 <span class="req-mark" title="必填">*</span>
            <span class="t-muted" style="font-size:11px">（多选；一个店铺只能属于一个费用配置）</span>
          </label>
          <div class="owner-pick" style="max-height:240px">
            <div v-if="!shops.length" class="t-muted" style="font-size:12px">
              暂无店铺。
            </div>
            <label v-for="s in shops" :key="s.id" class="owner-chip">
              <input type="checkbox" :checked="shopForm.shop_codes.includes(s.shop_code)" @change="toggleShopFormCode(s.shop_code)" />
              <span>
                {{ s.shop_name || s.shop_code }}
                <span v-if="shopCurrentFeeDept(s.shop_code)" class="dept-from">
                  ← {{ shopCurrentFeeDept(s.shop_code).name }}
                </span>
              </span>
            </label>
          </div>
        </div>

        <div class="error">{{ shopFormError }}</div>
      </div>
      <footer class="modal-foot">
        <button class="btn" @click="shopDialogOpen = false">取消</button>
        <button class="btn primary" @click="submitShop">保存</button>
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
.field-error { font-size: 12px; color: var(--neg); }
.field.has-error input, .field.has-error select {
  border-color: var(--neg);
  box-shadow: 0 0 0 3px oklch(56% 0.16 30 / 0.12);
}

.modal-backdrop {
  position: fixed; inset: 0; background: rgba(20, 20, 15, 0.45);
  display: grid; place-items: center; z-index: 80; backdrop-filter: blur(4px);
}
.modal-card {
  width: 560px; max-width: calc(100vw - 32px);
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
  width: 140px; padding: 8px 10px;
  border: 1px solid var(--border); border-radius: 8px;
  font-family: var(--font-mono); font-size: 14px; color: var(--ink);
  background: var(--surface);
}
.cfg-input input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-line); }
.cfg-input .suffix { color: var(--ink-4); font-family: var(--font-mono); font-size: 13px; }

.tabs-wrap { display: inline-flex; gap: 4px; padding: 4px; background: var(--bg-elev); border-radius: 10px; }
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

.more-tag {
  display: inline-flex; align-items: center;
  padding: 1px 7px; border-radius: 999px; margin-left: 4px;
  background: var(--bg-elev); color: var(--ink-3);
  font-size: 11px; font-family: var(--font-mono);
  cursor: help;
}

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
