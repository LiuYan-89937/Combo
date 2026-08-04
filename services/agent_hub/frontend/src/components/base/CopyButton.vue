<script setup lang="ts">
/*
 * Copy-to-clipboard control with a brief confirmed state and an aria-live
 * announcement. Falls back gracefully when the Clipboard API is unavailable.
 */
import { ref } from 'vue'
import BaseIcon from './BaseIcon.vue'
import { useI18n } from '@/i18n'

const props = defineProps<{ value: string; label?: string }>()
const { t } = useI18n()

const copied = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

async function copy() {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.value)
    } else {
      const area = document.createElement('textarea')
      area.value = props.value
      area.setAttribute('readonly', '')
      area.style.position = 'absolute'
      area.style.left = '-9999px'
      document.body.appendChild(area)
      area.select()
      document.execCommand('copy')
      document.body.removeChild(area)
    }
    copied.value = true
    clearTimeout(timer)
    timer = setTimeout(() => (copied.value = false), 1800)
  } catch {
    /* clipboard blocked — no-op, the value stays visible for manual copy */
  }
}
</script>

<template>
  <button
    type="button"
    class="copy-btn"
    :class="{ 'copy-btn--done': copied }"
    :aria-label="label ?? t('common.copy')"
    @click="copy"
  >
    <BaseIcon :name="copied ? 'check' : 'copy'" :size="16" />
    <span class="copy-btn__text">{{ copied ? t('common.copied') : t('common.copy') }}</span>
  </button>
  <span class="visually-hidden" role="status" aria-live="polite">
    {{ copied ? t('common.copied') : '' }}
  </span>
</template>

<style scoped>
.copy-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 36px;
  padding-inline: var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-family: inherit;
  font-size: 13px;
  font-weight: 550;
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
}
.copy-btn:hover {
  color: var(--text-strong);
  border-color: var(--text-secondary);
}
.copy-btn--done {
  color: var(--success);
  border-color: var(--success);
}
</style>
