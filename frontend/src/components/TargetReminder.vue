<script setup>
import { useRouter } from "vue-router";
import { useUserStore } from "../stores/user";
import { useTargetReminderStore } from "../stores/targetReminder";

const router = useRouter();
const userStore = useUserStore();
const reminder = useTargetReminderStore();

function goFill() {
  router.push({ name: "targets", query: { ym: reminder.yearMonth } });
}
</script>

<template>
  <transition name="reminder-pop">
    <div v-if="reminder.visible" class="reminder">
      <div class="reminder-head">
        <span class="reminder-dot" />
        <strong>业绩目标待填写</strong>
        <button class="reminder-x" @click="reminder.dismiss()" title="关闭">×</button>
      </div>
      <div class="reminder-body">
        临近月末，<b class="mono">{{ reminder.yearMonth }}</b> 还有
        <b>{{ reminder.missingCount }}</b> 位人员未设置业绩目标。
      </div>
      <div class="reminder-actions" v-if="userStore.canEditTargets">
        <button class="btn sm primary" @click="goFill">去填写</button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.reminder {
  position: fixed; right: 20px; bottom: 20px; z-index: 60;
  width: 300px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-pop); padding: 14px 14px 12px;
}
.reminder-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.reminder-dot {
  width: 8px; height: 8px; border-radius: 999px; background: #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.15);
}
.reminder-head strong { font-size: 13.5px; color: var(--ink); }
.reminder-x {
  margin-left: auto; border: 0; background: transparent; cursor: pointer;
  font-size: 18px; line-height: 1; color: var(--ink-3);
}
.reminder-x:hover { color: var(--ink); }
.reminder-body { font-size: 13px; color: var(--ink-2); line-height: 1.6; }
.reminder-actions { margin-top: 10px; display: flex; justify-content: flex-end; }
.reminder-pop-enter-active, .reminder-pop-leave-active { transition: opacity 0.2s, transform 0.2s; }
.reminder-pop-enter-from, .reminder-pop-leave-to { opacity: 0; transform: translateY(8px); }
</style>
