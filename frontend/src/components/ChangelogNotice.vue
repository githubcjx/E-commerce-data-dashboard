<script setup>
import { useChangelogStore } from "../stores/changelog";

// 部署后首次进入的更新提示。只有手动点 × 才消失（写入已读日期，
// 之后不再弹，直到 changelog.js 出现更新的日期）。没有自动关闭定时器。
const cl = useChangelogStore();

function viewAll() {
  // openModal 内部会标记已读，提示随之收起
  cl.openModal();
}
</script>

<template>
  <transition name="notice">
    <aside v-if="cl.noticeVisible" class="cl-notice" role="status">
      <header class="n-head">
        <span class="n-dot" />
        <span class="n-title">系统已更新</span>
        <button class="n-close" @click="cl.dismissNotice()" aria-label="关闭">×</button>
      </header>
      <div class="n-body">
        <div v-for="e in cl.unseenEntries" :key="e.date" class="n-entry">
          <div class="n-date mono">{{ e.date }}</div>
          <ul class="n-items">
            <li v-for="(it, i) in e.items" :key="i">{{ it }}</li>
          </ul>
        </div>
      </div>
      <footer class="n-foot">
        <button class="n-link" @click="viewAll">查看全部更新日志</button>
      </footer>
    </aside>
  </transition>
</template>

<style scoped>
.cl-notice {
  position: fixed; right: 24px; bottom: 24px; z-index: 110;
  width: min(380px, calc(100vw - 48px));
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: var(--shadow-pop);
  display: flex; flex-direction: column; overflow: hidden;
}
.n-head {
  display: flex; align-items: center; gap: 8px;
  padding: 12px 14px; border-bottom: 1px solid var(--divider);
}
.n-dot {
  width: 8px; height: 8px; border-radius: 999px; background: var(--accent);
  box-shadow: 0 0 0 3px var(--pos-soft); flex-shrink: 0;
}
.n-title { font-size: 13.5px; font-weight: 600; color: var(--ink); }
.n-close {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  margin-left: auto; font-size: 18px; line-height: 1; color: var(--ink-4);
  padding: 2px 6px; border-radius: 6px;
}
.n-close:hover { color: var(--ink); background: var(--surface-hover); }
.n-body { padding: 10px 14px; max-height: 40vh; overflow-y: auto; }
.n-entry + .n-entry { margin-top: 10px; }
.n-date {
  font-size: 11.5px; font-weight: 600; color: var(--ink-4);
  font-family: var(--font-mono); margin-bottom: 4px;
}
.n-items { margin: 0; padding-left: 16px; }
.n-items li { font-size: 12.5px; line-height: 1.6; color: var(--ink-2, var(--ink)); margin-top: 3px; }
.n-foot { padding: 8px 14px 12px; }
.n-link {
  appearance: none; border: 0; background: transparent; cursor: pointer;
  padding: 0; font-family: inherit; font-size: 12.5px; color: var(--accent-ink, var(--accent));
  text-decoration: underline; text-underline-offset: 3px;
}
.n-link:hover { opacity: 0.8; }

.notice-enter-from, .notice-leave-to { opacity: 0; transform: translateY(12px); }
.notice-enter-active, .notice-leave-active { transition: opacity 0.22s ease, transform 0.22s ease; }
</style>
