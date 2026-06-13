import { defineStore } from "pinia";
import { CHANGELOG, LATEST_DATE } from "../changelog";

// 右下角更新提示的已读标记。存"已读到的日志日期"而不是布尔值：
// 部署带来新日志日期（ISO 字符串可直接比大小）→ 自动重新弹出；
// 同一版本反复刷新 → 不再打扰。手动关闭才写入，没有自动消失。
const SEEN_KEY = "changelog_seen_date";

function readSeen() {
  try {
    return localStorage.getItem(SEEN_KEY) || "";
  } catch (_) {
    return ""; // localStorage 不可用（隐私模式等）→ 每次都提示，可接受
  }
}

export const useChangelogStore = defineStore("changelog", {
  state: () => ({
    modalOpen: false,
    seenDate: readSeen(),
  }),
  getters: {
    entries: () => CHANGELOG,
    latestEntry: () => CHANGELOG[0],
    // 比已读日期新的条目都算"本次更新"。从未看过（新设备/清过缓存）只推
    // 最新一天，避免把全部历史灌进一个小卡片。
    unseenEntries(state) {
      if (!state.seenDate) return [CHANGELOG[0]];
      return CHANGELOG.filter((e) => e.date > state.seenDate);
    },
    noticeVisible(state) {
      return state.seenDate < LATEST_DATE;
    },
  },
  actions: {
    openModal() {
      this.modalOpen = true;
      // 打开完整日志等于看过了最新内容 — 顺手收掉右下角提示
      this.dismissNotice();
    },
    closeModal() {
      this.modalOpen = false;
    },
    dismissNotice() {
      this.seenDate = LATEST_DATE;
      try {
        localStorage.setItem(SEEN_KEY, LATEST_DATE);
      } catch (_) { /* 存不进去就下次再提示 */ }
    },
  },
});
