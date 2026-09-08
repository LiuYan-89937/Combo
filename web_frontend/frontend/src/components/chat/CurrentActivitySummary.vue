<template>
  <div
    class="current-activity-summary"
    :class="[`activity-${activity.status}`, `activity-kind-${activity.kind}`]"
    role="status"
    aria-live="polite"
    :aria-label="activity.text"
  >
    <div class="current-activity-heading">
      <ComboFrameAnimation
        character="lead"
        action="running"
        :size="22"
        aria-hidden="true"
      />
      <span class="current-activity-text">{{ activity.text }}</span>
      <span v-if="elapsedText" class="current-activity-elapsed">{{ elapsedText }}</span>
    </div>


  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import type { ConversationActivitySummary } from '@/composables/conversation/useConversationMessageProjection'

const props = defineProps<{
  activity: ConversationActivitySummary
}>()
const now = ref(Date.now())
let elapsedTimer: number | undefined
const elapsedText = computed(() => {
  if (props.activity.kind !== 'computer_use' || !props.activity.startedAt) return ''
  const startedAt = Date.parse(props.activity.startedAt)
  if (!Number.isFinite(startedAt)) return ''
  const elapsedSeconds = Math.max(0, Math.floor((now.value - startedAt) / 1000))
  if (elapsedSeconds < 60) return `${elapsedSeconds}s`
  return `${Math.floor(elapsedSeconds / 60)}m ${elapsedSeconds % 60}s`
})
onMounted(() => {
  elapsedTimer = window.setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (elapsedTimer !== undefined) window.clearInterval(elapsedTimer)
})
</script>

<style scoped>
.current-activity-summary { display: inline-block; max-width: min(72vw, 720px); min-height: 22px; padding: 2px 8px 3px 50px; color: var(--app-text-tertiary); font-size: 12px; line-height: 18px; }
.current-activity-heading { display: flex; align-items: center; gap: 8px; }
.current-activity-text { min-width: 0; overflow-wrap: anywhere; }
.current-activity-elapsed { flex-shrink: 0; font-variant-numeric: tabular-nums; }
</style>
