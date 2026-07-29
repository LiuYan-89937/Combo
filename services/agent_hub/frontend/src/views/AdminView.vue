<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import AppReleaseManager from '@/components/admin/AppReleaseManager.vue'
import AgentReviewManager from '@/components/admin/AgentReviewManager.vue'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import StateBlock from '@/components/base/StateBlock.vue'
import { useAuthStore } from '@/stores/auth'
import { useSeo } from '@/composables/useSeo'

const auth = useAuthStore()
const { user, resolved, loading, isAuthenticated, isAdmin } = storeToRefs(auth)
const tab = ref<'app' | 'agents'>('app')

useSeo(() => ({
  title: '管理控制台',
  description: 'FastAgentFactory 应用发布与 AgentHub 审核控制台。',
  path: '/admin',
  noindex: true,
}))

onMounted(() => auth.ensure())
</script>

<template>
  <div class="admin">
    <section class="admin__hero">
      <div class="container admin__hero-inner">
        <div>
          <span class="eyebrow">Administration</span>
          <h1>管理控制台</h1>
          <p>管理桌面应用版本、更新日志与 AgentHub 审核。</p>
        </div>
        <span v-if="user" class="admin__identity">
          <img v-if="user.avatar_url" :src="user.avatar_url" alt="" width="32" height="32" />
          {{ user.github_login }}
        </span>
      </div>
    </section>

    <main class="container admin__body">
      <StateBlock v-if="!resolved && loading" kind="loading" title="正在确认管理员身份" />
      <section v-else-if="!isAuthenticated" class="gate">
        <span><BaseIcon name="github" :size="28" /></span>
        <h2>登录管理控制台</h2>
        <p>请使用已加入管理员白名单的 GitHub 账号登录。</p>
        <BaseButton icon="github" size="lg" @click="auth.login('/admin')">
          使用 GitHub 登录
        </BaseButton>
      </section>
      <StateBlock
        v-else-if="!isAdmin"
        kind="error"
        title="没有管理员权限"
        body="当前 GitHub 账号不在管理员白名单中。"
      />
      <template v-else>
        <nav class="tabs" aria-label="管理功能">
          <button
            type="button"
            :class="{ 'tabs__active': tab === 'app' }"
            @click="tab = 'app'"
          >
            应用发布
          </button>
          <button
            type="button"
            :class="{ 'tabs__active': tab === 'agents' }"
            @click="tab = 'agents'"
          >
            Agent 包审核
          </button>
        </nav>
        <AppReleaseManager v-if="tab === 'app'" />
        <AgentReviewManager v-else />
      </template>
    </main>
  </div>
</template>

<style scoped>
.admin__hero {
  padding-block: var(--space-12);
  border-bottom: 1px solid var(--border);
}
.admin__hero-inner {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-6);
}
.admin__hero h1 {
  margin: var(--space-2) 0 0;
  color: var(--text-strong);
  font-size: clamp(2rem, 4vw, 3.5rem);
  line-height: 1;
  letter-spacing: -0.055em;
}
.admin__hero p {
  margin-top: var(--space-3);
  color: var(--text-secondary);
}
.admin__identity {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-secondary);
  font-size: 13px;
}
.admin__identity img {
  border-radius: 50%;
}
.admin__body {
  padding-block: var(--space-8) var(--space-24);
}
.tabs {
  display: inline-flex;
  gap: var(--space-1);
  margin-bottom: var(--space-6);
  padding: 3px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-subtle);
}
.tabs button {
  height: 38px;
  padding-inline: var(--space-4);
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.tabs button.tabs__active {
  background: var(--surface);
  color: var(--text-strong);
  box-shadow: var(--shadow-soft);
}
.gate {
  display: grid;
  justify-items: center;
  max-width: 560px;
  margin: var(--space-12) auto;
  padding: var(--space-12);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  text-align: center;
}
.gate > span {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-md);
  background: var(--surface-subtle);
}
.gate h2 {
  margin: var(--space-4) 0 var(--space-2);
  color: var(--text-strong);
}
.gate p {
  margin-bottom: var(--space-6);
  color: var(--text-secondary);
}
</style>
