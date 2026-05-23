<script setup>
import { computed, onMounted, ref, watch } from "vue";
import FilterBar from "../components/FilterBar.vue";
import DraggableGrid from "../components/DraggableGrid.vue";
import DraggableSection from "../components/DraggableSection.vue";
import TrendPanel from "../components/TrendPanel.vue";
import CategoryTable from "../components/CategoryTable.vue";
import { useDashboardStore } from "../stores/dashboard";
import { useUiStore } from "../stores/ui";
import { useUserStore } from "../stores/user";

const store = useDashboardStore();
const ui = useUiStore();
const userStore = useUserStore();

const metricDefs = computed(() => store.kpiItems.map((it) => ({ key: it.key, label: it.label, format: it.format })));
const trendPoints = computed(() => store.trendPoints || []);

const secDragIdx = ref(null);
const secOverIdx = ref(null);

function onSecStart(i) { secDragIdx.value = i; }
function onSecEnter(i) {
  if (secDragIdx.value === null || secDragIdx.value === i) return;
  secOverIdx.value = i;
}
function onSecDrop(i) {
  const from = secDragIdx.value;
  if (from !== null && from !== i) {
    const next = store.sectionOrder.slice();
    const [moved] = next.splice(from, 1);
    next.splice(i, 0, moved);
    store.sectionOrder = next;
    store.persistLayout();
  }
  secDragIdx.value = null;
  secOverIdx.value = null;
}
function onSecEnd() { secDragIdx.value = null; secOverIdx.value = null; }

function onOrderUpdate(newOrder) {
  store.panelOrder = newOrder;
  store.persistLayout();
}
function onActive(key) {
  store.setActiveMetric(key);
}
function onReset() {
  store.resetLayout();
  ui.showToast("已重置面板顺序");
}

onMounted(async () => {
  // loadDepartments populates the 部门视角 picker. Only admin-tier roles
  // see / need it; tenant_user's call would 403 (noisy log + wasted RTT).
  const tasks = [store.loadFilters(), store.loadLayout()];
  if (userStore.isAdmin) tasks.push(store.loadDepartments());
  await Promise.all(tasks);
  await store.loadAll();
});

watch(() => store.activeMetric, () => store.loadTrend());
</script>

<template>
  <FilterBar @reset="onReset" />

  <DraggableGrid
    :order="store.panelOrder"
    :items="store.kpiItems"
    :active-key="store.activeMetric"
    @update:order="onOrderUpdate"
    @active="onActive"
  />

  <div class="stack">
    <template v-for="(key, idx) in store.sectionOrder" :key="key">
      <DraggableSection
        :index="idx"
        :drag-idx="secDragIdx"
        :over-idx="secOverIdx"
        @start="onSecStart"
        @enter="onSecEnter"
        @drop="onSecDrop"
        @end="onSecEnd"
      >
        <template #default="{ handleArmed }">
          <TrendPanel
            v-if="key === 'trend'"
            :active-key="store.activeMetric"
            :metric-defs="metricDefs"
            :points="trendPoints"
            @active="onActive"
          >
            <template #handle>
              <button
                class="drag-handle"
                title="拖动调整面板顺序"
                @mousedown="handleArmed(true)"
                @mouseup="handleArmed(false)"
                @mouseleave="handleArmed(false)"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="5" cy="3"  r="1" fill="currentColor"/>
                  <circle cx="9" cy="3"  r="1" fill="currentColor"/>
                  <circle cx="5" cy="7"  r="1" fill="currentColor"/>
                  <circle cx="9" cy="7"  r="1" fill="currentColor"/>
                  <circle cx="5" cy="11" r="1" fill="currentColor"/>
                  <circle cx="9" cy="11" r="1" fill="currentColor"/>
                </svg>
              </button>
            </template>
          </TrendPanel>
          <CategoryTable v-else-if="key === 'categoryTable'" :rows="store.categoryRows">
            <template #handle>
              <button
                class="drag-handle"
                title="拖动调整面板顺序"
                @mousedown="handleArmed(true)"
                @mouseup="handleArmed(false)"
                @mouseleave="handleArmed(false)"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <circle cx="5" cy="3"  r="1" fill="currentColor"/>
                  <circle cx="9" cy="3"  r="1" fill="currentColor"/>
                  <circle cx="5" cy="7"  r="1" fill="currentColor"/>
                  <circle cx="9" cy="7"  r="1" fill="currentColor"/>
                  <circle cx="5" cy="11" r="1" fill="currentColor"/>
                  <circle cx="9" cy="11" r="1" fill="currentColor"/>
                </svg>
              </button>
            </template>
          </CategoryTable>
        </template>
      </DraggableSection>
    </template>
  </div>
</template>
