<script setup>
import { useChangelogStore } from "../stores/changelog";

const cl = useChangelogStore();
</script>

<template>
  <teleport to="body">
    <transition name="cl-fade">
      <div v-if="cl.modalOpen" class="cl-mask" @click.self="cl.closeModal()">
        <div class="cl-dialog" role="dialog" aria-label="更新日志">
          <header class="cl-head">
            <span class="cl-title">更新日志</span>
            <button class="cl-close" @click="cl.closeModal()" aria-label="关闭">×</button>
          </header>
          <div class="cl-body">
            <section v-for="e in cl.entries" :key="e.date" class="cl-entry">
              <div class="cl-date mono">{{ e.date }}</div>
              <ul class="cl-items">
                <li v-for="(it, i) in e.items" :key="i">{{ it }}</li>
              </ul>
            </section>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<style scoped>
.cl-mask {
  position: fixed; inset: 0; z-index: 120;
  background: rgba(20, 20, 15, 0.35);
  display: grid; place-items: center; padding: 24px;
}
.cl-dialog {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-pop);
  width: min(560px, 100%); max-height: min(640px, 86vh);
  display: flex; flex-direction: column;
}
.cl-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px; border-bottom: 1px solid var(--divider);
}
.cl-title { font-size: 15px; font-weight: 600; color: var(--ink); }
.cl-close {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  font-size: 20px; line-height: 1; color: var(--ink-4); padding: 2px 6px;
  border-radius: 6px;
}
.cl-close:hover { color: var(--ink); background: var(--surface-hover); }
.cl-body { overflow-y: auto; padding: 6px 18px 18px; }
.cl-entry { padding-top: 14px; }
.cl-entry + .cl-entry { margin-top: 14px; border-top: 1px dashed var(--divider); }
.cl-date {
  font-size: 12.5px; font-weight: 600; color: var(--ink-3);
  font-family: var(--font-mono); margin-bottom: 6px;
}
.cl-items { margin: 0; padding-left: 18px; }
.cl-items li {
  font-size: 13px; line-height: 1.65; color: var(--ink);
  margin-top: 4px;
}

.cl-fade-enter-from, .cl-fade-leave-to { opacity: 0; }
.cl-fade-enter-active, .cl-fade-leave-active { transition: opacity 0.18s ease; }
</style>
