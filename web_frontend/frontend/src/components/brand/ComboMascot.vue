<template>
  <span
    class="combo-mascot"
    :class="{ 'is-working': state === 'working', 'is-compact': compact }"
    role="img"
    :aria-label="ariaLabel || 'Combo'"
  >
    <template v-if="state === 'working'">
      <ComboFrameAnimation
        character="lead"
        action="running"
        :size="size * 0.72"
        :paused="paused"
        :fps="fps"
      />
      <ComboFrameAnimation
        character="companion"
        action="running"
        :size="size * 0.48"
        :paused="paused"
        :fps="fps"
        :phase-offset="2"
      />
    </template>
    <ComboFrameAnimation
      v-else
      character="paired"
      :action="state"
      :size="size"
      :paused="paused"
      :fps="fps"
    />
  </span>
</template>

<script setup lang="ts">
import ComboFrameAnimation from './ComboFrameAnimation.vue'
import type { ComboMascotState } from './comboMascotAssets'

withDefaults(defineProps<{
  state?: ComboMascotState
  size?: number
  compact?: boolean
  ariaLabel?: string
  paused?: boolean
  fps?: number
}>(), {
  state: 'idle',
  size: 144,
  compact: false,
  ariaLabel: '',
  paused: false,
  fps: 0,
})

export type { ComboMascotState } from './comboMascotAssets'
</script>

<style scoped>
.combo-mascot {
  display: inline-flex;
  flex: none;
  align-items: flex-end;
  justify-content: center;
}

.combo-mascot.is-working {
  gap: calc(var(--app-space-1) * -1);
}

.combo-mascot.is-working > :last-child {
  margin-left: -8%;
}
</style>
