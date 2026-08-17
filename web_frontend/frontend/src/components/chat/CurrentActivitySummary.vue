<template>
  <div
    class="current-activity-summary"
    :class="`activity-${activity.status}`"
    role="status"
    aria-live="polite"
    :aria-label="activity.text"
  >
    <ComboFrameAnimation
      character="lead"
      action="running"
      :size="22"
      aria-hidden="true"
    />
    <span class="current-activity-text">{{ activity.text }}</span>
  </div>
</template>

<script setup lang="ts">
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import type { ConversationActivitySummary } from '@/composables/conversation/useConversationMessageProjection'

defineProps<{
  activity: ConversationActivitySummary
}>()
</script>

<style scoped>
.current-activity-summary {
  display: inline-flex;
  align-items: flex-start;
  gap: 7px;
  max-width: min(72vw, 720px);
  min-height: 24px;
  padding: 2px var(--app-space-md);
  color: var(--app-text-tertiary);
  font-size: 12px;
  line-height: 18px;
}

.current-activity-text {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}
</style>
