<script setup>
import { computed, onMounted, ref } from "vue";
import * as XLSX from "xlsx";
import { uploadFile, listBatches, getBatch, rollbackBatch } from "../api/import";
import { useUiStore } from "../stores/ui";

const ui = useUiStore();
const inputRef = ref(null);
const isOver = ref(false);
const parsing = ref(false);    // client-side xlsx parsing
const uploading = ref(false);  // POST /api/import/upload
const processing = ref(false); // server batch == "processing" (polling)
const loadingMsg = ref("");
const preview = ref(null);
const workbook = ref(null);
const history = ref([]);
const polling = ref(null);

// Any of these → full-screen blocking overlay.
const isBusy = computed(() => parsing.value || uploading.value || processing.value);

async function handleFile(file) {
  if (!file) return;
  parsing.value = true;
  loadingMsg.value = "正在解析 Excel…";
  try {
    const buf = await file.arrayBuffer();
    const wb = XLSX.read(buf, { type: "array", cellDates: true });
    workbook.value = wb;
    const firstSheet = wb.SheetNames[0];
    const ws = wb.Sheets[firstSheet];
    const json = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
    const [header = [], ...rows] = json;
    preview.value = {
      file,
      name: file.name,
      size: (file.size / 1024).toFixed(0) + " KB",
      rows: rows.length,
      columns: header,
      data: rows,
      sheetNames: wb.SheetNames,
      activeSheet: firstSheet,
    };
    ui.showToast(`已解析 ${file.name} · ${rows.length} 行`);
  } catch (err) {
    ui.showToast("文件解析失败：" + err.message, "error");
  } finally {
    parsing.value = false;
    loadingMsg.value = "";
  }
}

function switchSheet(name) {
  if (!workbook.value) return;
  const ws = workbook.value.Sheets[name];
  const json = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
  const [header = [], ...rows] = json;
  preview.value = { ...preview.value, activeSheet: name, columns: header, data: rows, rows: rows.length };
}

async function applyToDashboard() {
  if (!preview.value?.file) return;
  uploading.value = true;
  loadingMsg.value = "正在上传文件…";
  let batchId = null;
  try {
    const batch = await uploadFile(preview.value.file);
    batchId = batch.id;
    ui.showToast(`已上传 · 批次 ${batch.id.slice(0, 8)} 处理中`, "success");
    preview.value = null;
    workbook.value = null;
  } catch (err) {
    ui.showToast("上传失败：" + err.message, "error");
    uploading.value = false;
    loadingMsg.value = "";
    return;
  }
  uploading.value = false;
  processing.value = true;
  loadingMsg.value = "服务器正在解析并写入数据库…";
  pollBatch(batchId);
}

function pollBatch(id) {
  if (polling.value) clearInterval(polling.value);
  polling.value = setInterval(async () => {
    try {
      const b = await getBatch(id);
      if (b.status !== "processing") {
        clearInterval(polling.value);
        polling.value = null;
        processing.value = false;
        loadingMsg.value = "";
        refreshHistory();
        if (b.status === "success") {
          // Soft-skipped rows (parser-level) still show as success but include
          // a breakdown so the user can spot a total-vs-imported gap.
          const skipped = b.failed_rows || 0;
          const suffix = skipped ? ` · 跳过 ${skipped}（${b.error_message || ""}）` : "";
          ui.showToast(
            `导入完成 · 新增 ${b.inserted_rows} / 更新 ${b.updated_rows} / 总 ${b.total_rows}${suffix}`,
            skipped ? "warning" : "success"
          );
        } else {
          ui.showToast("导入失败：" + (b.error_message || "未知错误"), "error");
        }
      }
    } catch (_) { /* keep polling */ }
  }, 1500);
}

async function refreshHistory() {
  try { history.value = await listBatches(20); } catch (_) {}
}

async function rollback(batch) {
  // Accept either the batch object (preferred) or a bare id (legacy
  // callers). Resolving the filename up-front so the success toast can
  // identify which batch was rolled back — useful when there are many
  // entries in the history list.
  const id = typeof batch === "string" ? batch : batch?.id;
  const filename = typeof batch === "object" ? batch?.filename : null;
  if (!id) return;
  const label = filename ? `「${filename}」` : "此批次";
  if (!confirm(`确定回滚${label}？将删除该批次所有写入数据，且不可恢复。`)) return;
  try {
    const r = await rollbackBatch(id);
    // Defensive: server returns { deleted: N } but guard against unexpected shapes.
    const n = (r && typeof r.deleted === "number") ? r.deleted : 0;
    // Long-form, longer-lived toast so the user can clearly see the count.
    ui.showToast(
      filename
        ? `已回滚「${filename}」· 共删除 ${n.toLocaleString("zh-CN")} 行数据`
        : `已回滚 · 共删除 ${n.toLocaleString("zh-CN")} 行数据`,
      "success",
      4500,
    );
    refreshHistory();
  } catch (err) {
    ui.showToast("回滚失败：" + err.message, "error", 4500);
  }
}

function onDrop(e) {
  e.preventDefault();
  isOver.value = false;
  if (isBusy.value) return;
  const file = e.dataTransfer.files?.[0];
  if (file) handleFile(file);
}

function onPickClick() {
  if (isBusy.value) return;
  inputRef.value?.click();
}

onMounted(refreshHistory);
</script>

<template>
  <div class="stack">
    <div
      :class="['dropzone full', { 'is-over': isOver, 'is-disabled': isBusy }]"
      @dragover.prevent="isOver = true"
      @dragleave="isOver = false"
      @drop="onDrop"
      @click="onPickClick"
    >
      <div class="dropzone-icon">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M12 16V4M12 4L7 9M12 4L17 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M4 16V19C4 19.5523 4.44772 20 5 20H19C19.5523 20 20 19.5523 20 19V16" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
      <h3>拖拽 Excel 至此处或点击选择</h3>
      <p>支持 .xlsx / .xls · 单次最大 50MB · 首行作为表头</p>
      <input ref="inputRef" type="file" accept=".xlsx,.xls" style="display:none" @change="handleFile($event.target.files?.[0])" />
    </div>

    <div v-if="preview" class="preview-table-wrap">
      <header class="panel-head">
        <span class="panel-title">{{ preview.name }}</span>
        <span class="panel-subtitle">{{ preview.rows.toLocaleString() }} 行 · {{ preview.columns.length }} 列 · {{ preview.size }}</span>
        <div class="panel-actions" v-if="preview.sheetNames.length > 1" style="margin-left:16px">
          <button v-for="n in preview.sheetNames" :key="n" :class="['chip', { 'is-active': preview.activeSheet === n }]" @click="switchSheet(n)">{{ n }}</button>
        </div>
        <div class="panel-actions">
          <button class="btn sm" @click="preview = null; workbook = null">移除</button>
          <button class="btn primary sm" :disabled="isBusy" @click="applyToDashboard">应用到看板</button>
        </div>
      </header>
      <div class="preview-scroll">
        <table class="preview-tbl">
          <thead>
            <tr>
              <th class="row-num">#</th>
              <th v-for="(c, i) in preview.columns" :key="i">{{ c || `列 ${i + 1}` }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, ri) in preview.data.slice(0, 200)" :key="ri">
              <td class="row-num">{{ ri + 1 }}</td>
              <td v-for="(_, ci) in preview.columns" :key="ci">
                {{ row[ci] instanceof Date ? row[ci].toISOString().slice(0,10) : String(row[ci] ?? "") }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="preview.data.length > 200" style="padding:10px 22px;color:var(--ink-4);font-size:12px;border-top:1px solid var(--divider)">
        仅预览前 200 行，应用后将上传并解析全部 {{ preview.rows.toLocaleString() }} 行。
      </div>
    </div>

    <div class="upload-history">
      <header class="panel-head">
        <span class="panel-title">导入记录</span>
        <span class="panel-subtitle">最近 20 条</span>
      </header>
      <ul class="upload-history-list">
        <li v-for="h in history" :key="h.id">
          <span class="file-icon">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M3 1.5H8L11 4.5V12.5C11 12.7761 10.7761 13 10.5 13H3C2.72386 13 2.5 12.7761 2.5 12.5V2C2.5 1.72386 2.72386 1.5 3 1.5Z" stroke="currentColor" stroke-width="1.2"/>
              <path d="M8 1.5V4.5H11" stroke="currentColor" stroke-width="1.2"/>
            </svg>
          </span>
          <span class="file-name">{{ h.filename }}</span>
          <span :class="['tag', h.status === 'success' ? 'success' : h.status === 'failed' ? 'danger' : '']">
            {{ h.status === "processing" ? "处理中" : h.status === "success" ? "成功" : "失败" }}
          </span>
          <span class="spacer" />
          <span class="file-meta" :title="h.error_message || ''">
            新增 {{ h.inserted_rows }} · 更新 {{ h.updated_rows }}
            <template v-if="h.failed_rows"> · 跳过 {{ h.failed_rows }}</template>
            · 总 {{ h.total_rows }}
          </span>
          <span class="file-meta" style="width:160px;text-align:right">{{ new Date(h.created_at).toLocaleString("zh-CN", { hour12: false }) }}</span>
          <button class="btn ghost sm" @click="rollback(h)" :disabled="h.status === 'processing' || isBusy">回滚</button>
        </li>
        <li v-if="!history.length" class="empty-state" style="display:block">暂无导入记录</li>
      </ul>
    </div>

    <!-- Full-screen blocking loading overlay -->
    <Teleport to="body">
      <div v-if="isBusy" class="loading-overlay" @click.stop @mousedown.stop @keydown.stop>
        <div class="loading-card">
          <div class="spinner"></div>
          <div class="loading-msg">{{ loadingMsg || "处理中…" }}</div>
          <div class="loading-sub">请勿关闭页面或刷新</div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.dropzone.full { max-width: 100%; }
.dropzone.is-disabled { opacity: 0.55; pointer-events: none; cursor: not-allowed; }

.loading-overlay {
  position: fixed; inset: 0; z-index: 2000;
  background: rgba(20, 20, 15, 0.42);
  backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
  display: grid; place-items: center;
  cursor: wait;
  animation: fade-in .15s ease-out;
}
.loading-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  box-shadow: var(--shadow-pop);
  padding: 28px 36px; min-width: 280px;
  display: flex; flex-direction: column; align-items: center; gap: 14px;
}
.spinner {
  width: 36px; height: 36px; border-radius: 50%;
  border: 3px solid var(--divider);
  border-top-color: var(--accent);
  animation: spin .8s linear infinite;
}
.loading-msg { font-size: 14px; font-weight: 500; color: var(--ink); }
.loading-sub { font-size: 12px; color: var(--ink-4); }

@keyframes spin { to { transform: rotate(360deg); } }
@keyframes fade-in { from { opacity: 0; } to { opacity: 1; } }
</style>
