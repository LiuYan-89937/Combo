<template>
  <span class="control-hint">
    <slot />
    <span class="control-hint-content" role="tooltip">{{ label }}</span>
  </span>
</template>

<script setup lang="ts">
defineProps<{
  label: string
}>()
</script>

<style scoped>
.control-hint {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
}

.control-hint-content {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 50%;
  z-index: 12000;
  width: max-content;
  max-width: min(280px, calc(100vw - 32px));
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--app-text);
  box-shadow: var(--app-shadow-md);
  color: var(--app-surface);
  font-size: 12px;
  font-weight: 550;
  line-height: 1.35;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, 5px);
  transition: opacity .14s ease, transform .14s ease;
  white-space: normal;
}

.control-hint-content::after {
  position: absolute;
  top: 100%;
  left: 50%;
  width: 8px;
  height: 8px;
  background: var(--app-text);
  content: '';
  transform: translate(-50%, -4px) rotate(45deg);
}

.control-hint:hover .control-hint-content,
.control-hint:focus-within .control-hint-content {
  opacity: 1;
  transform: translate(-50%, 0);
}

@media (prefers-reduced-motion: reduce) {
  .control-hint-content {
    transition: none;
  }
}
</style>
