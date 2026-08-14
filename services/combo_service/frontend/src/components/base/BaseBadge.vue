<script setup lang="ts">
/*
 * Small status/label chip. Tone maps to the semantic tokens; the default
 * neutral tone is used for metadata so color stays reserved for real status.
 */
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'outline'
    size?: 'sm' | 'md'
  }>(),
  { tone: 'neutral', size: 'md' },
)
</script>

<template>
  <span class="badge" :class="[`badge--${tone}`, `badge--${size}`]">
    <slot />
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 3px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  font-size: 12px;
  font-weight: 550;
  line-height: 1.4;
  white-space: nowrap;
}
.badge--sm {
  padding: 2px 8px;
  font-size: 11px;
}
.badge--neutral {
  background: var(--surface-subtle);
  color: var(--text-secondary);
  border-color: var(--border);
}
.badge--outline {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border-strong);
}
.badge--success {
  background: var(--success-surface);
  color: var(--success);
}
.badge--warning {
  background: var(--warning-surface);
  color: var(--warning);
}
.badge--danger {
  background: var(--danger-surface);
  color: var(--danger);
}
</style>
