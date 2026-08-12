<template>
  <span class="sub-agent-mascot" role="img" :aria-label="ariaLabel || 'Sub Agent'">
    <ComboFrameAnimation
      v-if="celebrating"
      character="companion"
      action="jumping"
      :size="size"
      :loop="false"
      @complete="celebrating = false"
    />
    <ComboFrameAnimation
      v-else
      character="companion"
      :action="animation.action"
      :size="size"
      :paused="animation.paused || awaitingInput"
      :phase-offset="phaseOffset"
    />
  </span>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { BackgroundTaskStatus } from '@/api/backgroundTasks'
import ComboFrameAnimation from './ComboFrameAnimation.vue'
import type { ComboCharacterAction } from './comboMascotAssets'

const props = withDefaults(defineProps<{
  status: BackgroundTaskStatus
  taskId?: string
  size?: number
  ariaLabel?: string
  awaitingInput?: boolean
}>(), {
  taskId: '',
  size: 44,
  ariaLabel: '',
  awaitingInput: false,
})

const celebrating = ref(false)

const animation = computed<{ action: ComboCharacterAction; paused: boolean }>(() => {
  if (props.status === 'claimed' || props.status === 'running') {
    return { action: 'running', paused: false }
  }
  if (props.status === 'queued') {
    return { action: 'idle', paused: false }
  }
  return { action: 'idle', paused: true }
})

const phaseOffset = computed(() => stablePhase(props.taskId))

watch(
  () => props.status,
  (status, previous) => {
    celebrating.value = (
      (status === 'succeeded' && previous !== 'succeeded')
      || ((status === 'claimed' || status === 'running') && previous === 'queued')
    )
  },
)

function stablePhase(value: string): number {
  let hash = 0
  for (const character of value) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return hash
}
</script>

<style scoped>
.sub-agent-mascot {
  display: inline-grid;
  flex: none;
  place-items: center;
}
</style>
