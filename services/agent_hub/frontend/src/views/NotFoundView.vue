<script setup lang="ts">
import BaseButton from '@/components/base/BaseButton.vue'
import { useI18n } from '@/i18n'
import { useSeo } from '@/composables/useSeo'

const { t } = useI18n()
useSeo(() => ({ title: t('notFound.title'), path: '/404', noindex: true }))
</script>

<template>
  <div class="container not-found">
    <p class="not-found__code mono">404</p>
    <h1 class="not-found__title">{{ t('notFound.title') }}</h1>
    <p class="not-found__body">{{ t('notFound.body') }}</p>
    <div class="not-found__actions">
      <BaseButton to="/" icon-end="arrow-right">{{ t('notFound.goHome') }}</BaseButton>
    </div>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  min-height: 62vh;
  padding-block: var(--space-18);
  gap: var(--space-3);
}
.not-found__code {
  font-size: clamp(64px, 14vw, 128px);
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--surface-pressed);
}
.not-found__title {
  font-size: 26px;
  font-weight: 640;
  color: var(--text-strong);
}
.not-found__body {
  color: var(--text-secondary);
  max-width: 40ch;
}
.not-found__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
  margin-top: var(--space-4);
}
</style>
