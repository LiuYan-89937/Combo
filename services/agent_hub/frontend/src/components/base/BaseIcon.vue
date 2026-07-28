<script setup lang="ts">
/*
 * Inline icon set. Lucide-style geometry at 1.75px stroke, currentColor.
 * Keeping icons inline (vs a font or sprite request) means zero extra network
 * cost and perfect theming. Decorative by default; pass `title` for a labelled,
 * announced icon.
 */
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    name: IconName
    size?: number | string
    title?: string
  }>(),
  { size: 20 },
)

export type IconName =
  | 'arrow-right'
  | 'arrow-up-right'
  | 'download'
  | 'search'
  | 'github'
  | 'sun'
  | 'moon'
  | 'menu'
  | 'close'
  | 'check'
  | 'copy'
  | 'globe'
  | 'upload'
  | 'file-zip'
  | 'shield-check'
  | 'alert'
  | 'clock'
  | 'chevron-down'
  | 'chevron-right'
  | 'external'
  | 'cpu'
  | 'wrench'
  | 'boxes'
  | 'play'
  | 'users'
  | 'send'
  | 'spinner'
  | 'x-circle'

const PATHS: Record<IconName, string> = {
  'arrow-right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  'arrow-up-right': '<path d="M7 17 17 7"/><path d="M7 7h10v10"/>',
  download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  github:
    '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12 12 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="M18 6 6 18M6 6l12 12"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z"/>',
  upload: '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M5 3h14"/>',
  'file-zip':
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M15 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M11 7h.01M11 10h.01M11 13h.01"/>',
  'shield-check': '<path d="M12 3 5 6v5c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6Z"/><path d="m9 12 2 2 4-4"/>',
  alert: '<path d="M12 9v4m0 4h.01"/><path d="M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6A2 2 0 0 0 22 18L13.7 3.9a2 2 0 0 0-3.4 0Z"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  'chevron-down': '<path d="m6 9 6 6 6-6"/>',
  'chevron-right': '<path d="m9 6 6 6-6 6"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v2m6-2v2M9 20v2m6-2v2M2 9h2m-2 6h2m16-6h2m-2 6h2"/><rect x="10" y="10" width="4" height="4" rx="1"/>',
  wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.3 5.3L3 18l3 3 6.4-6.4a4 4 0 0 0 5.3-5.3l-2.5 2.5-2.8-.7-.7-2.8Z"/>',
  boxes: '<path d="M12 3 3 7.5 12 12l9-4.5Z"/><path d="M3 7.5v9L12 21m0-9v9m9-13.5v9L12 21"/>',
  play: '<path d="M7 4v16l13-8Z"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 5a3.5 3.5 0 0 1 0 6.5M21 20a6 6 0 0 0-4-5.6"/>',
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4Z"/>',
  spinner: '<path d="M12 3a9 9 0 1 0 9 9" />',
  'x-circle': '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
}

const dimension = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
</script>

<template>
  <svg
    class="base-icon"
    :class="{ 'base-icon--spin': name === 'spinner' }"
    :width="dimension"
    :height="dimension"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    :role="title ? 'img' : undefined"
    :aria-hidden="title ? undefined : 'true'"
    :aria-label="title"
    focusable="false"
    v-html="(title ? `<title>${title}</title>` : '') + PATHS[name]"
  />
</template>

<style scoped>
.base-icon {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
}
.base-icon--spin {
  animation: base-icon-spin 0.8s linear infinite;
  transform-origin: center;
}
@keyframes base-icon-spin {
  to {
    transform: rotate(360deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .base-icon--spin {
    animation-duration: 1.6s;
  }
}
</style>
