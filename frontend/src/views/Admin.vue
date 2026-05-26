<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  listUsers, createUser, updateUser, deleteUser, listTenantOwners,
} from "../api/users";
import {
  listDepartments, createDepartment, updateDepartment, deleteDepartment,
} from "../api/departments";
import {
  listShops, listFeeGroups, saveFeeGroup, deleteFeeGroup,
  listMonthlyCosts, saveMonthlyCosts,
} from "../api/shops";
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
const shops = ref([]);          // every shop in the tenant (per-shop)
const feeGroups = ref([]);      // aggregated by fee_group_name (店铺管理 list)
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
    feeGroups.value = [];
    return;
  }
  try {
    // Per-shop list AND aggregated fee-groups in parallel — the dialog
    // needs the full shop list (multi-select), the table needs groups.
    const [s, g] = await Promise.all([
      listShops(targetTenantId.value),
      listFeeGroups(targetTenantId.value),
    ]);
    shops.value = s;
    feeGroups.value = g;
  } catch (e) { ui.showToast(e.message || "店铺加载失败", "error"); }
}

async function loadOwners() {
  // Anyone with backend access can read the owner list: super + platform
  // for full UI, plain admin for the display-name combobox AND (when
  // their can_manage_scope flag is on) the data-scope picker. Used to
  // gate this on canManageUsers, which was too narrow — it left plain
  // admins with an empty 指定负责人 list even after super-admin granted
  // them the scope-management permission.
  if (!userStore.isAdmin) return;
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
  // Only meaningful when role === tenant_admin. Hidden from the form
  // otherwise. Editable only by super.
  can_manage_scope: false,
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
    can_manage_scope: false,
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
    can_manage_scope: !!u.can_manage_scope,
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

// Whether the data_scope_owners picker is visible in the current dialog:
//  - Super / platform: always visible when the form has privileged controls
//  - Plain admin: only when editing a tenant_user AND their own
//    can_manage_scope flag is on
//  - The field is hidden for super-admin targets (they're never restricted)
const showScopeField = computed(() => {
  if (!dialogOpen.value) return false;
  // The field controls data_scope_owners which only applies to tenant_user.
  const targetRole = editing.value ? editing.value.role : form.value.role;
  if (targetRole !== ROLE_TENANT_USER) return false;
  if (userStore.isPlatformAdmin || userStore.isTenantSuperAdmin) return true;
  if (userStore.isTenantPlainAdmin) return !!userStore.user?.can_manage_scope;
  return false;
});

// Whether to show the "can_manage_scope" toggle on this form. Only when
// editing/creating a tenant_admin target AND the actor is super-class.
const canToggleManageScope = computed(() => {
  if (!dialogOpen.value) return false;
  const targetRole = editing.value ? editing.value.role : form.value.role;
  if (targetRole !== ROLE_TENANT_ADMIN) return false;
  return dialogAllowsPrivileged.value;
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
      }
      // Data-scope edit: super always allowed; plain admin only when their
      // own can_manage_scope flag is set. Show-and-send under the same
      // gate as the field's visibility (see showScopeField).
      if (showScopeField.value) {
        const newScope = form.value.scope_mode === "all" ? null : form.value.scope_owners.slice();
        const oldScope = editing.value.data_scope_owners ?? null;
        if (JSON.stringify(newScope) !== JSON.stringify(oldScope)) {
          body.data_scope_owners = newScope;
        }
      }
      // can_manage_scope toggle — super-only field.
      if (dialogAllowsPrivileged.value && form.value.role === ROLE_TENANT_ADMIN
          && !!form.value.can_manage_scope !== !!editing.value.can_manage_scope) {
        body.can_manage_scope = !!form.value.can_manage_scope;
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
      if (form.value.role === ROLE_TENANT_ADMIN) {
        body.can_manage_scope = !!form.value.can_manage_scope;
      }
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
// Fee-group dialog (店铺管理). One row in the list = one fee group.
// ---------------------------------------------------------------------------
const shopDialogOpen = ref(false);
const editingGroup = ref(null);  // the fee-group being edited (null = create)
// 固定费用 (formerly per_capita_share) is now per-month — edited via the
// separate "按月费用" dialog. This form keeps only name + tax_rate + member
// shops; per-month amounts live in fee_group_monthly_cost on the backend.
const shopForm = ref({
  fee_group_name: "",
  ship_service_tax_rate_pct: "0",
  shop_codes: [],
});
const shopFormError = ref("");
const shopFeeGroupErr = ref("");
const shopTaxErr = ref("");

function resetShopErrors() {
  shopFormError.value = "";
  shopFeeGroupErr.value = "";
  shopTaxErr.value = "";
}

function openShopCreate() {
  editingGroup.value = null;
  shopForm.value = {
    fee_group_name: "",
    ship_service_tax_rate_pct: "0",
    shop_codes: [],
  };
  resetShopErrors();
  shopDialogOpen.value = true;
}

// Edit a fee-group: pre-populate name, values, and the member shop list
// from the group's current state.
function openShopEdit(group) {
  editingGroup.value = group;
  shopForm.value = {
    fee_group_name: group.name,
    ship_service_tax_rate_pct: (Number(group.ship_service_tax_rate || 0) * 100).toFixed(2).replace(/\.?0+$/, ""),
    shop_codes: (group.shops || []).map((s) => s.shop_code),
  };
  resetShopErrors();
  shopDialogOpen.value = true;
}

function toggleShopFormCode(code) {
  const arr = shopForm.value.shop_codes;
  const i = arr.indexOf(code);
  if (i === -1) arr.push(code); else arr.splice(i, 1);
}

// Hint chip for the picker: which OTHER group currently owns this shop.
// Hidden when the shop is in the group being edited (no conflict there).
function shopCurrentFeeGroup(shopCode) {
  if (!shopCode) return null;
  const s = shops.value.find((x) => x.shop_code === shopCode);
  if (!s || !s.fee_group_name) return null;
  // If this shop already belongs to the group we're editing, no warning.
  if (editingGroup.value && s.fee_group_name === editingGroup.value.name) return null;
  // If the input matches the existing label (same group), no warning.
  if ((s.fee_group_name || "").trim() === (shopForm.value.fee_group_name || "").trim()) return null;
  return s.fee_group_name;
}

function validateShopForm() {
  let ok = true;
  const label = (shopForm.value.fee_group_name || "").trim();
  shopForm.value.fee_group_name = label;
  if (!label) { shopFeeGroupErr.value = "请填写费用所属部门名称"; ok = false; }
  else if (label.length > 100) { shopFeeGroupErr.value = "名称不能超过 100 个字符"; ok = false; }
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
    name: shopForm.value.fee_group_name,
    ship_service_tax_rate: Number(shopForm.value.ship_service_tax_rate_pct) / 100,
    shop_codes: shopForm.value.shop_codes.slice(),
  };
  // On edit, pass the original name so the backend can reconcile members
  // (shops removed from the multi-select get cleared), accept renames,
  // AND cascade the rename to fee_group_monthly_cost rows.
  if (editingGroup.value) body.original_name = editingGroup.value.name;
  try {
    const r = await saveFeeGroup(body, targetTenantId.value);
    const msg = r.removed
      ? `已保存：${r.applied} 个店铺应用配置，${r.removed} 个店铺移出`
      : `已保存：${r.applied} 个店铺应用配置`;
    ui.showToast(msg, "success");
    shopDialogOpen.value = false;
    await refreshShops();
  } catch (e) {
    shopFormError.value = e.message || "保存失败";
  }
}

// ---------------------------------------------------------------------------
// Per-month 固定费用 dialog
// ---------------------------------------------------------------------------
// One row per month from the tenant's earliest imported data month → 当月,
// guaranteed to exist (the backend pads missing months with 0). Users can
// only EDIT amounts — no add / no delete / no rearrange.
const monthlyDialogOpen = ref(false);
const monthlyGroupName = ref("");        // which group we're editing
const monthlyRows = ref([]);             // [{year_month, amount, is_current_month, original}]
const monthlyLoading = ref(false);
const monthlySaving = ref(false);
const monthlyError = ref("");

// Display order: most recent month at top; the backend returns ascending.
const monthlyRowsDesc = computed(() => monthlyRows.value.slice().reverse());

// Did any row's amount diverge from what we loaded? Drives the save button.
const monthlyDirtyCount = computed(
  () => monthlyRows.value.filter((r) => Number(r.amount) !== Number(r.original)).length,
);

async function openMonthlyDialog(group) {
  monthlyGroupName.value = group.name;
  monthlyDialogOpen.value = true;
  monthlyError.value = "";
  monthlyLoading.value = true;
  monthlyRows.value = [];
  try {
    const data = await listMonthlyCosts(group.name, targetTenantId.value);
    monthlyRows.value = (data.rows || []).map((r) => ({
      year_month: r.year_month,
      amount: Number(r.amount || 0),
      is_current_month: !!r.is_current_month,
      original: Number(r.amount || 0),  // snapshot for dirty-tracking
    }));
  } catch (e) {
    monthlyError.value = e.message || "加载失败";
  } finally {
    monthlyLoading.value = false;
  }
}

function onMonthlyAmountInput(row, raw) {
  // Allow empty string (treated as 0); reject non-numbers / negatives.
  const v = raw === "" || raw == null ? 0 : Number(raw);
  if (!Number.isFinite(v) || v < 0) return;
  row.amount = v;
}

async function submitMonthly() {
  if (monthlyDirtyCount.value === 0) {
    monthlyDialogOpen.value = false;
    return;
  }
  // Send only changed rows — smaller payload AND skips no-op work in the
  // backend's diff path.
  const items = monthlyRows.value
    .filter((r) => Number(r.amount) !== Number(r.original))
    .map((r) => ({ year_month: r.year_month, amount: Number(r.amount) }));
  monthlySaving.value = true;
  monthlyError.value = "";
  try {
    const r = await saveMonthlyCosts(monthlyGroupName.value, items, targetTenantId.value);
    ui.showToast(`已保存 ${r.saved || 0} 处变更`, "success");
    // Re-snapshot originals so the dirty count clears.
    for (const row of monthlyRows.value) row.original = row.amount;
    // Refresh the table — current-month cost on the main list might have changed.
    await refreshShops();
    monthlyDialogOpen.value = false;
  } catch (e) {
    monthlyError.value = e.message || "保存失败";
  } finally {
    monthlySaving.value = false;
  }
}

function cancelMonthly() {
  if (monthlyDirtyCount.value > 0
      && !confirm(`放弃 ${monthlyDirtyCount.value} 处未保存的修改？`)) {
    return;
  }
  monthlyDialogOpen.value = false;
}

// Delete a whole fee group — clears the (name, values) bundle off every
// shop currently in the group. The shop rows themselves stay (they come
// from imports); they'll re-appear in the list once added to a new group.
async function removeFeeGroup(group) {
  const n = (group.shops || []).length;
  if (!confirm(`确认删除「${group.name}」？将清除 ${n} 个店铺的费用配置。`)) return;
  try {
    await deleteFeeGroup(group.name, targetTenantId.value);
    ui.showToast("已删除", "success");
    await refreshShops();
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
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
            <span
              v-if="u.role === 'tenant_admin' && u.can_manage_scope"
              class="tag" style="margin-left:6px"
              title="超级管理员已授权该管理员修改普通用户的数据查看范围"
            >可改数据范围</span>
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
    <!-- One row per fee group (= per distinct fee_group_name). Member
         shops live behind the 编辑 dialog; per-month 固定费用 amounts
         live behind the 按月费用 dialog. -->
    <table v-else class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">费用所属部门</th>
          <th style="text-align:left">本月固定费用</th>
          <th style="text-align:left">百分比费用（发货客服税费）</th>
          <th style="text-align:left">适用店铺数</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:left">更新时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="g in feeGroups" :key="g.name">
          <td style="text-align:left">{{ g.name }}</td>
          <td style="text-align:left" class="mono">
            <template v-if="g.current_month_cost != null">
              {{ Number(g.current_month_cost).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }}
              <span class="t-muted" style="font-size:11px;font-family:var(--font-sans)"> · {{ g.current_month }}</span>
            </template>
            <template v-else>
              <span class="t-muted">—</span>
              <span class="t-muted" style="font-size:11px"> （{{ g.current_month }} 未录入，按 0 计）</span>
            </template>
          </td>
          <td style="text-align:left" class="mono">{{ (Number(g.ship_service_tax_rate || 0) * 100).toFixed(2).replace(/\.?0+$/, '') }}%</td>
          <td style="text-align:left">
            <span :title="(g.shops || []).map((s) => s.shop_name || s.shop_code).join('、')">
              {{ (g.shops || []).length }} 个
            </span>
          </td>
          <td style="text-align:left" class="t-muted">{{ new Date(g.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td style="text-align:left" class="t-muted">{{ new Date(g.updated_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button v-if="canManageShops" class="btn ghost sm" @click="openMonthlyDialog(g)">按月费用</button>
            <button v-if="canManageShops" class="btn ghost sm" @click="openShopEdit(g)">编辑</button>
            <button
              v-if="canManageShops"
              class="btn ghost sm" @click="removeFeeGroup(g)"
              style="color:var(--neg)"
            >删除</button>
            <span v-if="!canManageShops" class="t-muted" style="font-size:12px">—</span>
          </td>
        </tr>
        <tr v-if="!feeGroups.length">
          <td colspan="7" class="empty-state">
            暂无费用配置，请点击「+ 新增费用配置」开始
          </td>
        </tr>
      </tbody>
    </table>
  </section>

  <!-- =================== USER DIALOG =================== -->
  <!-- Backdrop is non-dismissive across all modals: clicking outside
       doesn't close, to protect unsaved edits. ✕ / Cancel only. -->
  <div v-if="dialogOpen" class="modal-backdrop">
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
        </template>

        <!-- Scope picker — only applies to tenant_user; super always sees
             it, plain admin only when their own permission flag is on. -->
        <div v-if="showScopeField" class="field">
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

        <!-- Super-admin-only switch: grant this admin the right to edit
             普通用户's data_scope_owners. The wrapping label captures
             clicks across the whole card; the on/off state is also
             surfaced as a "已授权 / 未授权" pill so the user never has
             to squint at a tiny native checkbox. -->
        <div v-if="canToggleManageScope" class="field">
          <label>数据查看范围操作权限</label>
          <label class="perm-card" :class="{ 'is-on': form.can_manage_scope }">
            <input
              type="checkbox"
              :checked="form.can_manage_scope"
              @change="form.can_manage_scope = $event.target.checked"
            />
            <span class="perm-box" aria-hidden="true">
              <svg v-if="form.can_manage_scope" width="14" height="14" viewBox="0 0 14 14" fill="none">
                <path d="M3 7L6 10L11 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
            <span class="perm-body">
              <span class="perm-title">
                {{ form.can_manage_scope ? '已授权 — 可修改普通用户的数据查看范围' : '未授权 — 不能修改普通用户的数据查看范围' }}
                <span :class="['perm-pill', form.can_manage_scope ? 'on' : 'off']">
                  {{ form.can_manage_scope ? '开' : '关' }}
                </span>
              </span>
              <span class="perm-hint">
                关闭后，该管理员在用户管理中只能改普通用户的显示名 / 部门。
              </span>
            </span>
          </label>
        </div>

        <div class="error">{{ formError }}</div>
      </div>
      <footer class="modal-foot">
        <button class="btn" @click="dialogOpen = false">取消</button>
        <button class="btn primary" @click="submit">保存</button>
      </footer>
    </div>
  </div>

  <!-- =================== DEPARTMENT DIALOG =================== -->
  <div v-if="deptDialogOpen" class="modal-backdrop">
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
  <div v-if="shopDialogOpen" class="modal-backdrop">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editingGroup ? "编辑费用配置" : "新增费用配置" }}</span>
        <button class="btn ghost sm" @click="shopDialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field" :class="{ 'has-error': shopFeeGroupErr }">
          <label>
            费用所属部门名称 <span class="req-mark" title="必填">*</span>
            <span class="t-muted" style="font-size:11px">（自由填写，仅用于列表分组展示）</span>
          </label>
          <input
            v-model="shopForm.fee_group_name"
            placeholder="例如：财务一组"
            maxlength="100"
            @input="shopFeeGroupErr = ''"
          />
          <div v-if="shopFeeGroupErr" class="field-error">{{ shopFeeGroupErr }}</div>
        </div>

        <div class="field-note">
          <strong>固定费用（人员均摊）</strong>已改为按月录入。请在列表的「按月费用」按钮中设置每个月的总额。
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
                <span v-if="shopCurrentFeeGroup(s.shop_code)" class="dept-from">
                  ← {{ shopCurrentFeeGroup(s.shop_code) }}
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

  <!-- =================== MONTHLY COST DIALOG =================== -->
  <!-- Rows are data-driven: backend returns one row per calendar month
       from the tenant's earliest imported data through the current month.
       Users only EDIT amounts — no add/remove/rearrange. -->
  <div v-if="monthlyDialogOpen" class="modal-backdrop">
    <div class="modal-card monthly-card">
      <header class="modal-head">
        <span class="panel-title">按月固定费用 — {{ monthlyGroupName }}</span>
        <button class="btn ghost sm" @click="cancelMonthly">✕</button>
      </header>
      <div class="modal-body">
        <div class="field-note">
          每行对应一个自然月（从导入数据中最早的月份到当月）。
          未录入或设为 0 的月份按 0 计算，不参与公司利润率扣除。
          底部为最早的月份，可逐月补齐。
        </div>

        <div v-if="monthlyLoading" class="t-muted" style="padding:12px 0">加载中…</div>

        <table v-else class="tbl monthly-tbl">
          <thead>
            <tr>
              <th style="text-align:left;width:140px">月份</th>
              <th style="text-align:left">固定费用总额（元）</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in monthlyRowsDesc" :key="row.year_month"
                :class="{ 'is-current': row.is_current_month,
                          'is-dirty': Number(row.amount) !== Number(row.original) }">
              <td style="text-align:left">
                <span class="mono">{{ row.year_month }}</span>
                <span v-if="row.is_current_month" class="month-chip">本月</span>
              </td>
              <td>
                <div class="cfg-input">
                  <input
                    type="number" min="0" step="0.01"
                    :value="row.amount"
                    @input="onMonthlyAmountInput(row, $event.target.value)"
                  />
                  <span class="suffix">元</span>
                  <span v-if="Number(row.amount) !== Number(row.original)" class="dirty-dot" title="未保存的修改"></span>
                </div>
              </td>
            </tr>
            <tr v-if="!monthlyRows.length">
              <td colspan="2" class="empty-state">
                暂无可编辑的月份（请先导入销售数据，确定起始月份）。
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="monthlyError" class="error">{{ monthlyError }}</div>
      </div>
      <footer class="modal-foot">
        <span class="t-muted" style="font-size:12px;margin-right:auto">
          <template v-if="monthlyDirtyCount > 0">{{ monthlyDirtyCount }} 处未保存的修改</template>
          <template v-else>无未保存修改</template>
        </span>
        <button class="btn" :disabled="monthlySaving" @click="cancelMonthly">取消</button>
        <button
          class="btn primary"
          :disabled="monthlySaving || monthlyDirtyCount === 0"
          @click="submitMonthly"
        >{{ monthlySaving ? "保存中…" : "保存" }}</button>
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

/* Inline notice replacing the removed 人员均摊 input — directs admins to
   the 按月费用 dialog. Soft accent surface to read as informational, not
   error. */
.field-note {
  padding: 10px 12px; margin-bottom: 14px;
  background: var(--accent-soft); border: 1px solid var(--accent-line);
  border-radius: 8px; font-size: 12.5px; color: var(--ink-2); line-height: 1.55;
}
.field-note strong { color: var(--ink); font-weight: 600; }

/* Monthly-cost dialog: wider modal, scrollable table, current-month
   highlight, dirty-row tint, "未保存" dot on changed inputs. */
.monthly-card { width: 520px; }
.monthly-tbl { margin-top: 4px; }
.monthly-tbl th, .monthly-tbl td { padding: 8px 10px; }
.monthly-tbl tr.is-current td { background: var(--accent-soft); }
.monthly-tbl tr.is-dirty td { background: oklch(95% 0.04 80 / 0.6); }
.month-chip {
  display: inline-block; margin-left: 8px;
  padding: 1px 8px; border-radius: 999px;
  font-size: 10.5px; font-family: var(--font-mono); font-weight: 600;
  letter-spacing: 0.04em; color: #fff; background: var(--accent);
}
.dirty-dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: oklch(70% 0.18 80); flex-shrink: 0;
}
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

/* Card-style permission toggle — large click target, obvious on/off state */
.perm-card {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface); cursor: pointer;
  transition: border-color .15s, background .15s, box-shadow .15s;
}
.perm-card:hover { border-color: var(--border-strong); }
.perm-card.is-on {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: 0 0 0 3px var(--accent-line);
}
/* Hide the native checkbox visually but keep it in the DOM for accessibility */
.perm-card input[type="checkbox"] {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0);
  white-space: nowrap; border: 0;
}
.perm-box {
  flex-shrink: 0; width: 22px; height: 22px;
  display: inline-flex; align-items: center; justify-content: center;
  border: 1.5px solid var(--border-strong); border-radius: 6px;
  background: var(--surface); color: transparent;
  transition: background .15s, border-color .15s, color .15s;
}
.perm-card.is-on .perm-box {
  background: var(--accent); border-color: var(--accent); color: #fff;
}
.perm-body { display: flex; flex-direction: column; gap: 4px; }
.perm-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; font-weight: 500; color: var(--ink);
}
.perm-card.is-on .perm-title { color: var(--accent-ink); }
.perm-hint { font-size: 11px; color: var(--ink-4); }
.perm-pill {
  font-size: 10.5px; padding: 1px 8px; border-radius: 999px;
  font-family: var(--font-mono); font-weight: 600; letter-spacing: 0.04em;
}
.perm-pill.on  { background: var(--accent); color: #fff; }
.perm-pill.off { background: var(--bg-elev); color: var(--ink-4); }
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
