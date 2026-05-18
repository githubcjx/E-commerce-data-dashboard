<script setup>
import GripIcon from "./GripIcon.vue";
defineProps({ visible: Boolean });
</script>

<template>
  <div :class="['drag-hint', { 'is-visible': visible }]">
    <GripIcon />
    松开以放置在此处
  </div>
</template>
