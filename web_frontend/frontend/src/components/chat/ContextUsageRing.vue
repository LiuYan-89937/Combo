<template>
  <span
    class="context-usage-ring"
    :class="{
      'is-unknown': usagePercent === null,
      'is-compressing': compressionAnimating,
    }"
    :style="ringStyle"
    :aria-label="label"
    role="img"
  >
    <span>{{ ringLabel }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import type { ContextWindowView } from '@/types/protocol'
import { contextWindowUsageLabel, contextWindowUsagePercent } from '@/utils/contextWindowMeter'

const props = withDefaults(defineProps<{
  value?: ContextWindowView | null
  size?: number
}>(), {
  value: null,
  size: 32,
})

const usagePercent = computed(() => props.value ? contextWindowUsagePercent(props.value) : null)
const compressionAnimating = ref(false)
let compressionTimer: number | null = null
const ringLabel = computed(() => {
  if (usagePercent.value === null) return '–'
  if (usagePercent.value > 0 && usagePercent.value < 1) return '<1'
  return `${Math.round(usagePercent.value)}`
})
const label = computed(() => props.value ? contextWindowUsageLabel(props.value) : 'Context usage unavailable')
const ringStyle = computed<CSSProperties>(() => ({
  '--context-ring-size': `${props.size}px`,
  '--context-ring-progress': `${usagePercent.value ?? 0}%`,
}))

watch(
  () => [props.value?.compressionStatus, props.value?.source, props.value?.updatedAt].join(':'),
  () => {
    const compressionEvent = props.value?.compressionStatus === 'running'
      || props.value?.compressionStatus === 'completed'
      || props.value?.source?.includes('compression')
    if (!compressionEvent) return
    if (compressionTimer !== null) window.clearTimeout(compressionTimer)
    compressionAnimating.value = false
    window.requestAnimationFrame(() => {
      compressionAnimating.value = true
      compressionTimer = window.setTimeout(() => {
        compressionAnimating.value = false
        compressionTimer = null
      }, 900)
    })
  },
)

onBeforeUnmount(() => {
  if (compressionTimer !== null) window.clearTimeout(compressionTimer)
})
</script>

<style scoped>
.context-usage-ring {
  position: relative;
  display: grid;
  width: var(--context-ring-size);
  height: var(--context-ring-size);
  flex: 0 0 var(--context-ring-size);
  place-items: center;
  border-radius: 50%;
  background: conic-gradient(var(--app-text) var(--context-ring-progress), var(--app-divider) 0);
  color: var(--app-text);
}
.context-usage-ring::after {
  position: absolute;
  inset: 2px;
  border-radius: inherit;
  background: var(--app-surface);
  content: '';
}
.context-usage-ring > span { position: relative; z-index: 1; font-size: 8px; font-weight: 750; }
.context-usage-ring.is-unknown { opacity: .5; }
.context-usage-ring.is-compressing { animation: context-compress .9s cubic-bezier(.16, 1, .3, 1) both; }
@keyframes context-compress {
  0% { transform: scale(1); }
  32% { transform: scale(.68) rotate(-16deg); }
  62% { transform: scale(1.12) rotate(4deg); }
  100% { transform: scale(1) rotate(0); }
}
@media (prefers-reduced-motion: reduce) {
  .context-usage-ring.is-compressing { animation: none; }
}
</style>
