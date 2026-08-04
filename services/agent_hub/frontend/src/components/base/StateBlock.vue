<script setup lang="ts">
/*
 * Shared empty / error / loading placeholder. Keeps every view's non-happy
 * paths visually consistent. `kind` picks the icon and role; error blocks may
 * expose a retry action and an optional request id for support.
 */
import BaseIcon, { type IconName } from './BaseIcon.vue'
import BaseButton from './BaseButton.vue'
import { useI18n } from '@/i18n'

const props = withDefaults(
  defineProps<{
    kind?: 'empty' | 'error' | 'loading'
    icon?: IconName
    title?: string
    body?: string
    requestId?: string
    retryable?: boolean
  }>(),
  { kind: 'empty' },
)

const emit = defineEmits<{ retry: [] }>()
const { t } = useI18n()

const iconName = (): IconName => {
  if (props.icon) return props.icon
  if (props.kind === 'error') return 'alert'
  if (props.kind === 'loading') return 'spinner'
  return 'boxes'
}
</script>

<template>
  <div class="state" :role="kind === 'error' ? 'alert' : 'status'">
    <span class="state__icon" :class="`state__icon--${kind}`">
      <BaseIcon :name="iconName()" :size="26" />
    </span>
    <p v-if="title" class="state__title">{{ title }}</p>
    <p v-if="body" class="state__body">{{ body }}</p>
    <p v-if="requestId" class="state__meta mono">
      {{ t('common.requestId') }}: {{ requestId }}
    </p>
    <BaseButton
      v-if="retryable"
      variant="secondary"
      size="sm"
      icon="arrow-right"
      class="state__retry"
      @click="emit('retry')"
    >
      {{ t('common.retry') }}
    </BaseButton>
  </div>
</template>

<style scoped>
.state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--space-3);
  padding: var(--space-18) var(--space-6);
}
.state__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: var(--radius-lg);
  background: var(--surface-subtle);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}
.state__icon--error {
  color: var(--danger);
  background: var(--danger-surface);
  border-color: transparent;
}
.state__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-strong);
}
.state__body {
  max-width: 44ch;
  color: var(--text-secondary);
}
.state__meta {
  font-size: 12px;
  color: var(--text-muted);
}
.state__retry {
  margin-top: var(--space-2);
}
</style>
