<script setup>
import { computed, onMounted, watch } from "vue";
import { useRoute, RouterView } from "vue-router";
import TopBar from "./components/TopBar.vue";
import ToastHost from "./components/ToastHost.vue";
import DragHint from "./components/DragHint.vue";
import UpdateBanner from "./components/UpdateBanner.vue";
import TargetReminder from "./components/TargetReminder.vue";
import ChangelogModal from "./components/ChangelogModal.vue";
import ChangelogNotice from "./components/ChangelogNotice.vue";
import { useUiStore } from "./stores/ui";
import { useUserStore } from "./stores/user";
import { useVersionStore } from "./stores/version";
import { useTargetReminderStore } from "./stores/targetReminder";
import { hasToken } from "./api/client";

const route = useRoute();
const ui = useUiStore();
const userStore = useUserStore();
const versionStore = useVersionStore();
const targetReminder = useTargetReminderStore();

const showChrome = computed(() => route.name !== "login");

function maybeStartReminder() {
  // Only tenant admins get the 月末目标 reminder; platform admin has no tenant.
  if (userStore.isAdmin && !userStore.isPlatformAdmin) targetReminder.start();
}

onMounted(() => {
  // If we have a token but no user info cached (e.g. after a schema upgrade
  // or a hard refresh), backfill from /api/auth/me so role-gated UI shows up.
  if (hasToken() && !userStore.user) {
    userStore.refresh();
  }
  // Start polling /version.json so users get a banner when we ship a new
  // frontend build. See stores/version.js for cadence + behavior.
  versionStore.startPolling();
  maybeStartReminder();
});

// The user object may be backfilled async (refresh) after mount — start the
// reminder poll once the role is known. start() is idempotent.
watch(() => userStore.user?.role, maybeStartReminder);
</script>

<template>
  <UpdateBanner />
  <TopBar v-if="showChrome" />
  <main class="shell" v-if="showChrome">
    <RouterView />
  </main>
  <RouterView v-else />
  <DragHint :visible="ui.isDragging" />
  <ToastHost />
  <TargetReminder />
  <ChangelogModal />
  <!-- 更新提示只在登录后的页面出现，登录页不打扰 -->
  <ChangelogNotice v-if="showChrome" />
</template>
