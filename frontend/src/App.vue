<script setup>
import { computed, onMounted } from "vue";
import { useRoute, RouterView } from "vue-router";
import TopBar from "./components/TopBar.vue";
import ToastHost from "./components/ToastHost.vue";
import DragHint from "./components/DragHint.vue";
import UpdateBanner from "./components/UpdateBanner.vue";
import { useUiStore } from "./stores/ui";
import { useUserStore } from "./stores/user";
import { useVersionStore } from "./stores/version";
import { hasToken } from "./api/client";

const route = useRoute();
const ui = useUiStore();
const userStore = useUserStore();
const versionStore = useVersionStore();

const showChrome = computed(() => route.name !== "login");

onMounted(() => {
  // If we have a token but no user info cached (e.g. after a schema upgrade
  // or a hard refresh), backfill from /api/auth/me so role-gated UI shows up.
  if (hasToken() && !userStore.user) {
    userStore.refresh();
  }
  // Start polling /version.json so users get a banner when we ship a new
  // frontend build. See stores/version.js for cadence + behavior.
  versionStore.startPolling();
});
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
</template>
