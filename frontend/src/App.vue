<script setup>
import { computed, onMounted } from "vue";
import { useRoute, RouterView } from "vue-router";
import TopBar from "./components/TopBar.vue";
import ToastHost from "./components/ToastHost.vue";
import DragHint from "./components/DragHint.vue";
import { useUiStore } from "./stores/ui";
import { useUserStore } from "./stores/user";
import { hasToken } from "./api/client";

const route = useRoute();
const ui = useUiStore();
const userStore = useUserStore();

const showChrome = computed(() => route.name !== "login");

// If we have a token but no user info cached (e.g. after a schema upgrade or a
// hard refresh), backfill from /api/auth/me so the role-gated UI shows up.
onMounted(() => {
  if (hasToken() && !userStore.user) {
    userStore.refresh();
  }
});
</script>

<template>
  <TopBar v-if="showChrome" />
  <main class="shell" v-if="showChrome">
    <RouterView />
  </main>
  <RouterView v-else />
  <DragHint :visible="ui.isDragging" />
  <ToastHost />
</template>
