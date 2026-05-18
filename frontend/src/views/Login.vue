<script setup>
import { ref } from "vue";
import { useRouter } from "vue-router";
import { useUserStore } from "../stores/user";

const router = useRouter();
const userStore = useUserStore();

const username = ref("");
const password = ref("");
const error = ref("");
const submitting = ref(false);

async function onSubmit() {
  error.value = "";
  submitting.value = true;
  try {
    await userStore.login(username.value, password.value);
    router.push({ name: "dashboard" });
  } catch (e) {
    error.value = e.message || "登录失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-shell">
    <form class="login-card" @submit.prevent="onSubmit">
      <div class="brand">
        <span class="brand-mark">EC</span>
        <span class="brand-name">电商经营看板</span>
        <span class="brand-tag">· v1.0</span>
      </div>
      <h2>登录</h2>
      <p class="hint">请输入账号与密码</p>
      <div class="field">
        <label>账号</label>
        <input
          type="text"
          v-model="username"
          autocomplete="username"
          placeholder="username"
        />
      </div>
      <div class="field">
        <label>密码</label>
        <input
          type="password"
          v-model="password"
          autocomplete="current-password"
          placeholder="••••••"
        />
      </div>
      <div class="error">{{ error }}</div>
      <button class="btn primary" type="submit" :disabled="submitting || !username || !password">
        {{ submitting ? "正在登录…" : "登录" }}
      </button>
    </form>
  </div>
</template>
