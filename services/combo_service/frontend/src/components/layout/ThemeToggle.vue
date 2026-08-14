<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import BaseIcon from '@/components/base/BaseIcon.vue'
import { useThemeStore } from '@/stores/theme'
import { useI18n } from '@/i18n'

const store = useThemeStore()
const { theme } = storeToRefs(store)
const { t } = useI18n()
const isDark = computed(() => theme.value === 'dark')
</script>

<template>
  <button
    type="button"
    class="icon-btn"
    :aria-label="t('nav.theme')"
    :aria-pressed="isDark"
    @click="store.toggle()"
  >
    <BaseIcon :name="isDark ? 'sun' : 'moon'" :size="19" />
  </button>
</template>

<style scoped>
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.icon-btn:hover {
  background: var(--surface-subtle);
  color: var(--text-strong);
}
</style>
