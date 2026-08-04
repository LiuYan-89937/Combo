<script setup lang="ts">
import { storeToRefs } from 'pinia'
import BaseIcon from '@/components/base/BaseIcon.vue'
import { useI18nStore } from '@/i18n'

const store = useI18nStore()
const { locale } = storeToRefs(store)
</script>

<template>
  <button
    type="button"
    class="lang-btn"
    :aria-label="store.t('nav.language')"
    @click="store.toggleLocale()"
  >
    <BaseIcon name="globe" :size="18" />
    <span class="lang-btn__text mono">{{ locale === 'zh' ? '中' : 'EN' }}</span>
  </button>
</template>

<style scoped>
.lang-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 40px;
  padding-inline: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text);
  font-family: inherit;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.lang-btn:hover {
  background: var(--surface-subtle);
  color: var(--text-strong);
}
.lang-btn__text {
  font-size: 13px;
  font-weight: 600;
}
</style>
