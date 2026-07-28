<script setup lang="ts">
/*
 * OAuth return landing. GitHub login redirects here; we re-check the session
 * (the server has just set the HttpOnly cookie) and then forward the user to
 * their intended destination — defaulting to the publish center. A ?status=
 * hint from the backend lets us show a failure state without a session probe.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BaseButton from '@/components/base/BaseButton.vue'
import BaseIcon from '@/components/base/BaseIcon.vue'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const phase = ref<'processing' | 'success' | 'failed'>('processing')

function safeReturnTo(): string {
  const raw = route.query.return_to
  const value = typeof raw === 'string' ? raw : ''
  // Only allow same-origin absolute paths to avoid open-redirects.
  if (value.startsWith('/') && !value.startsWith('//')) return value
  return '/publish'
}

useSeo(() => ({ title: t('auth.processing'), path: '/auth/result', noindex: true }))

onMounted(async () => {
  const status = route.query.status
  if (status === 'error' || status === 'failed') {
    phase.value = 'failed'
    return
  }
  const user = await auth.refresh()
  if (user) {
    phase.value = 'success'
    const target = safeReturnTo()
    setTimeout(() => router.replace(target), 600)
  } else {
    phase.value = 'failed'
  }
})
</script>

<template>
  <div class="container auth-result">
    <div class="card">
      <template v-if="phase === 'processing'">
        <span class="card__icon"><BaseIcon name="spinner" :size="28" /></span>
        <h1 class="card__title">{{ t('auth.processing') }}</h1>
        <p class="card__body">{{ t('auth.processingBody') }}</p>
      </template>

      <template v-else-if="phase === 'success'">
        <span class="card__icon card__icon--ok"><BaseIcon name="check" :size="28" /></span>
        <h1 class="card__title">{{ t('auth.success') }}</h1>
        <div class="card__actions">
          <BaseButton to="/publish" icon-end="arrow-right">{{ t('auth.goPublish') }}</BaseButton>
        </div>
      </template>

      <template v-else>
        <span class="card__icon card__icon--err"><BaseIcon name="x-circle" :size="28" /></span>
        <h1 class="card__title">{{ t('auth.failed') }}</h1>
        <p class="card__body">{{ t('auth.failedBody') }}</p>
        <div class="card__actions">
          <BaseButton icon="github" @click="auth.login('/publish')">{{ t('publish.loginButton') }}</BaseButton>
          <BaseButton to="/hub" variant="secondary">{{ t('auth.goHub') }}</BaseButton>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.auth-result {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  padding-block: var(--space-18);
}
.card {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  max-width: 440px;
  padding: var(--space-12) var(--space-8);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  background: var(--surface);
}
.card__icon {
  display: inline-grid;
  place-items: center;
  width: 60px;
  height: 60px;
  border-radius: var(--radius-lg);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  color: var(--text-strong);
  margin-bottom: var(--space-2);
}
.card__icon--ok {
  color: var(--success);
  background: var(--success-surface);
  border-color: transparent;
}
.card__icon--err {
  color: var(--danger);
  background: var(--danger-surface);
  border-color: transparent;
}
.card__title {
  font-size: 24px;
  font-weight: 640;
  color: var(--text-strong);
}
.card__body {
  color: var(--text-secondary);
}
.card__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
</style>
