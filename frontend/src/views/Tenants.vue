<script setup>
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { listTenants, createTenant, updateTenant, deleteTenant } from "../api/tenants";
import { useUiStore } from "../stores/ui";

const ui = useUiStore();
const router = useRouter();

const tenants = ref([]);
const loading = ref(false);

const dialogOpen = ref(false);
const editing = ref(null);
const form = ref({
  code: "", name: "",
  admin_username: "", admin_password: "", admin_display_name: "",
  status: "active",
});
const formError = ref("");

async function refresh() {
  loading.value = true;
  try { tenants.value = await listTenants(); }
  catch (e) { ui.showToast(e.message || "加载失败", "error"); }
  finally { loading.value = false; }
}

function openCreate() {
  editing.value = null;
  form.value = { code: "", name: "", admin_username: "", admin_password: "", admin_display_name: "", status: "active" };
  formError.value = "";
  dialogOpen.value = true;
}
function openEdit(t) {
  editing.value = t;
  form.value = { code: t.code, name: t.name, status: t.status, admin_username: "", admin_password: "", admin_display_name: "" };
  formError.value = "";
  dialogOpen.value = true;
}

async function submit() {
  formError.value = "";
  try {
    if (editing.value) {
      await updateTenant(editing.value.id, { name: form.value.name, status: form.value.status });
      ui.showToast("已更新", "success");
    } else {
      if (!form.value.code || !form.value.name || !form.value.admin_username || !form.value.admin_password) {
        formError.value = "企业短码、名称、首位管理员账号 / 密码均必填";
        return;
      }
      await createTenant({
        code: form.value.code,
        name: form.value.name,
        admin_username: form.value.admin_username,
        admin_password: form.value.admin_password,
        admin_display_name: form.value.admin_display_name || null,
      });
      ui.showToast("已创建", "success");
    }
    dialogOpen.value = false;
    await refresh();
  } catch (e) {
    formError.value = e.message || "保存失败";
  }
}

async function remove(t) {
  if (!confirm(`确认删除企业「${t.name}」？该企业全部用户、批次、销售数据都将被级联删除，无法恢复！`)) return;
  try {
    await deleteTenant(t.id);
    ui.showToast("已删除", "success");
    await refresh();
  } catch (e) {
    ui.showToast(e.message || "删除失败", "error");
  }
}

function manageUsers(t) {
  router.push({ name: "users-admin", query: { tenant_id: t.id, tenant_code: t.code, tenant_name: t.name } });
}

onMounted(refresh);
</script>

<template>
  <section class="panel">
    <header class="panel-head">
      <span class="panel-title">企业管理</span>
      <span class="panel-subtitle">共 {{ tenants.length }} 家企业</span>
      <div class="panel-actions">
        <button class="btn primary sm" @click="openCreate">+ 新增企业</button>
      </div>
    </header>
    <table class="tbl">
      <thead>
        <tr>
          <th style="text-align:left">短码</th>
          <th style="text-align:left">名称</th>
          <th style="text-align:left">状态</th>
          <th>用户数</th>
          <th style="text-align:left">创建时间</th>
          <th style="text-align:right">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in tenants" :key="t.id">
          <td class="mono">{{ t.code }}</td>
          <td style="text-align:left">{{ t.name }}</td>
          <td style="text-align:left">
            <span :class="['tag', t.status === 'active' ? 'success' : 'danger']">
              {{ t.status === 'active' ? '启用' : '已停用' }}
            </span>
          </td>
          <td>{{ t.user_count }}</td>
          <td style="text-align:left" class="t-muted">{{ new Date(t.created_at).toLocaleString("zh-CN", { hour12: false }) }}</td>
          <td>
            <button class="btn ghost sm" @click="manageUsers(t)">用户</button>
            <button class="btn ghost sm" @click="openEdit(t)">编辑</button>
            <button class="btn ghost sm" @click="remove(t)" style="color:var(--neg)">删除</button>
          </td>
        </tr>
        <tr v-if="!loading && !tenants.length">
          <td colspan="6" class="empty-state">暂无企业 — 点「新增企业」开通第一家</td>
        </tr>
      </tbody>
    </table>
  </section>

  <div v-if="dialogOpen" class="modal-backdrop" @click.self="dialogOpen = false">
    <div class="modal-card">
      <header class="modal-head">
        <span class="panel-title">{{ editing ? "编辑企业" : "新增企业 + 首位管理员" }}</span>
        <button class="btn ghost sm" @click="dialogOpen = false">✕</button>
      </header>
      <div class="modal-body">
        <div class="field">
          <label>企业短码 <span class="t-muted" style="font-size:11px">（小写字母/数字/-/_，全局唯一）</span></label>
          <input :disabled="!!editing" v-model="form.code" placeholder="acme" />
        </div>
        <div class="field">
          <label>企业名称</label>
          <input v-model="form.name" placeholder="杭州某某科技有限公司" />
        </div>
        <div v-if="editing" class="field">
          <label>状态</label>
          <select class="select" v-model="form.status">
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </select>
        </div>

        <template v-if="!editing">
          <hr style="margin:16px 0;border:0;border-top:1px solid var(--divider)" />
          <div style="font-size:12px;color:var(--ink-3);margin-bottom:10px">为该企业配置一位初始管理员，企业方使用此账号登录：</div>
          <div class="field">
            <label>管理员账号</label>
            <input v-model="form.admin_username" placeholder="alice" />
          </div>
          <div class="field">
            <label>管理员密码</label>
            <input type="password" v-model="form.admin_password" placeholder="至少 6 位" />
          </div>
          <div class="field">
            <label>显示名（可选）</label>
            <input v-model="form.admin_display_name" placeholder="Alice 张" />
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
  display: grid; place-items: center; z-index: 80;
  backdrop-filter: blur(4px);
}
.modal-card {
  width: 480px; max-width: calc(100vw - 32px);
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  box-shadow: var(--shadow-pop);
  display: flex; flex-direction: column; max-height: 90vh;
}
.modal-head, .modal-foot {
  padding: 14px 18px; display: flex; align-items: center; gap: 12px;
  border-bottom: 1px solid var(--divider);
}
.modal-foot { border-bottom: 0; border-top: 1px solid var(--divider); justify-content: flex-end; }
.modal-body { padding: 18px; overflow-y: auto; }
.error { font-size: 12px; color: var(--neg); min-height: 16px; }
</style>
