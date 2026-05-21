<script setup>
import { useVersionStore } from "../stores/version";

const v = useVersionStore();
</script>

<template>
  <transition name="banner">
    <div v-if="v.updateAvailable" class="update-banner" role="alert">
      <div class="msg">
        <span class="dot" />
        <span>系统已发布新版本，建议刷新以使用最新功能</span>
      </div>
      <div class="actions">
        <button class="btn-link" @click="v.dismiss()">稍后</button>
        <button class="btn-cta" @click="v.reload()">立即刷新</button>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.update-banner {
  position: fixed; top: 0; left: 0; right: 0;
  z-index: 100;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 10px 22px;
  background: var(--accent);
  color: #fff;
  font-size: 13px; line-height: 1.4;
  box-shadow: 0 2px 10px rgba(20, 20, 15, 0.18);
}
.msg { display: inline-flex; align-items: center; gap: 10px; }
.dot {
  width: 8px; height: 8px; border-radius: 50%;
  background: #fff; flex-shrink: 0;
  animation: pulse 1.6s ease-in-out infinite;
}
.actions { display: inline-flex; gap: 8px; flex-shrink: 0; }
.btn-link, .btn-cta {
  font-family: inherit; cursor: pointer;
  border-radius: 6px; font-size: 12.5px;
  transition: background 0.15s, color 0.15s;
}
.btn-link {
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.35);
  color: rgba(255, 255, 255, 0.88); padding: 5px 12px;
}
.btn-link:hover { background: rgba(255, 255, 255, 0.1); color: #fff; }
.btn-cta {
  background: #fff; border: 1px solid #fff;
  color: var(--accent-ink); font-weight: 600; padding: 5px 14px;
}
.btn-cta:hover { background: rgba(255, 255, 255, 0.92); }

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 255, 255, 0.55); }
  50%      { box-shadow: 0 0 0 6px rgba(255, 255, 255, 0); }
}

.banner-enter-from, .banner-leave-to { transform: translateY(-100%); }
.banner-enter-active, .banner-leave-active { transition: transform 0.25s ease; }

@media (max-width: 640px) {
  .update-banner { padding: 8px 14px; font-size: 12px; }
  .msg span:not(.dot) {
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
    overflow: hidden;
  }
}
</style>
