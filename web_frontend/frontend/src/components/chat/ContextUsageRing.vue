<template>
  <span
    class="context-usage-ring"
    :class="{ 'is-unknown': usagePercent === null }"
    :style="ringStyle"
    :aria-label="label"
    role="img"
  >
    <span>{{ ringLabel }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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
const ringLabel = computed(() => usagePercent.value === null ? '–' : `${Math.round(usagePercent.value)}`)
const label = computed(() => props.value ? contextWindowUsageLabel(props.value) : 'Context usage unavailable')
const ringStyle = computed<CSSProperties>(() => ({
  '--context-ring-size': `${props.size}px`,
  '--context-ring-progress': `${usagePercent.value ?? 0}%`,
}))
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
</style>
