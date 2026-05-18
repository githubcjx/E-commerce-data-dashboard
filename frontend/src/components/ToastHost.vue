<script setup>
import { useUiStore } from "../stores/ui";
const ui = useUiStore();
</script>

<template>
  <div :class="['toast', { 'is-visible': !!ui.toast }, ui.toast?.kind || '']">
    <span class="toast-dot" />
    <span>{{ ui.toast?.msg }}</span>
  </div>
</template>
