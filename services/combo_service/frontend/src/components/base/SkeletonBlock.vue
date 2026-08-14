<script setup lang="ts">
/*
 * Content-shaped loading placeholder. Respects prefers-reduced-motion (the
 * shimmer is disabled globally in reset.css). Marked aria-hidden; a sibling
 * aria-live region should announce "loading" for assistive tech.
 */
withDefaults(
  defineProps<{
    width?: string
    height?: string
    radius?: string
    block?: boolean
  }>(),
  { width: '100%', height: '16px', radius: 'var(--radius-sm)' },
)
</script>

<template>
  <span
    class="skeleton"
    :class="{ 'skeleton--block': block }"
    :style="{ width, height, borderRadius: radius }"
    aria-hidden="true"
  />
</template>

<style scoped>
.skeleton {
  display: inline-block;
  background: linear-gradient(
    90deg,
    var(--surface-subtle) 25%,
    var(--surface-pressed) 37%,
    var(--surface-subtle) 63%
  );
  background-size: 400% 100%;
  animation: skeleton-shimmer 1.4s ease infinite;
}
.skeleton--block {
  display: block;
}
@keyframes skeleton-shimmer {
  0% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0 50%;
  }
}
@media (prefers-reduced-motion: reduce) {
  .skeleton {
    animation: none;
  }
}
</style>
