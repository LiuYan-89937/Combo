<script setup lang="ts">
/*
 * One button, three visual weights, rendered as <button>, <a> or <router-link>
 * so semantics always match intent. 40px minimum height keeps the touch target
 * accessible.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import BaseIcon, { type IconName } from './BaseIcon.vue'

const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost'
    size?: 'md' | 'lg' | 'sm'
    to?: string
    href?: string
    type?: 'button' | 'submit'
    disabled?: boolean
    loading?: boolean
    block?: boolean
    icon?: IconName
    iconEnd?: IconName
    external?: boolean
  }>(),
  { variant: 'primary', size: 'md', type: 'button' },
)

const tag = computed(() => {
  if (props.to) return RouterLink
  if (props.href) return 'a'
  return 'button'
})

const bindings = computed(() => {
  if (props.to) return { to: props.to }
  if (props.href) {
    return {
      href: props.href,
      ...(props.external ? { target: '_blank', rel: 'noopener noreferrer' } : {}),
    }
  }
  return { type: props.type, disabled: props.disabled || props.loading }
})
</script>

<template>
  <component
    :is="tag"
    class="btn"
    :class="[
      `btn--${variant}`,
      `btn--${size}`,
      { 'btn--block': block, 'btn--loading': loading, 'btn--disabled': disabled },
    ]"
    :aria-busy="loading ? 'true' : undefined"
    :aria-disabled="disabled ? 'true' : undefined"
    v-bind="bindings"
  >
    <BaseIcon v-if="loading" name="spinner" :size="18" class="btn__spinner" />
    <BaseIcon v-else-if="icon" :name="icon" :size="18" />
    <span class="btn__label"><slot /></span>
    <BaseIcon v-if="iconEnd && !loading" :name="iconEnd" :size="18" />
  </component>
</template>

<style scoped>
.btn {
  --btn-h: 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: var(--btn-h);
  padding-inline: var(--space-6);
  border: 1px solid transparent;
  border-radius: var(--radius-pill);
  font-family: inherit;
  font-size: 15px;
  font-weight: 550;
  line-height: 1;
  text-decoration: none;
  white-space: nowrap;
  cursor: pointer;
  user-select: none;
  transition: background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
}
.btn:active {
  transform: translateY(1px);
}

.btn--sm {
  --btn-h: 36px;
  padding-inline: var(--space-4);
  font-size: 14px;
}
.btn--lg {
  --btn-h: 52px;
  padding-inline: var(--space-8);
  font-size: 16px;
}
.btn--block {
  display: flex;
  width: 100%;
}

.btn--primary {
  background: var(--primary);
  color: var(--on-primary);
}
.btn--primary:hover {
  background: var(--primary-hover);
}

.btn--secondary {
  background: var(--surface);
  color: var(--text-strong);
  border-color: var(--border-strong);
}
.btn--secondary:hover {
  background: var(--surface-subtle);
  border-color: var(--text-secondary);
}

.btn--ghost {
  background: transparent;
  color: var(--text);
}
.btn--ghost:hover {
  background: var(--surface-subtle);
}

.btn--disabled,
.btn[disabled] {
  opacity: 0.45;
  pointer-events: none;
}
.btn--loading {
  pointer-events: none;
}
.btn__label:empty {
  display: none;
}
</style>
