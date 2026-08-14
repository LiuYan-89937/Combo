<template>
  <div class="tool-trace-message" :class="{ embedded }">
    <div v-if="!embedded" class="assistant-avatar" aria-hidden="true">
      <ComboFrameAnimation character="companion" action="idle" :size="34" paused />
    </div>
    <div class="trace-content">
      <div v-if="!embedded" class="trace-header">
        <strong>Combo</strong>
        <span>{{ formattedTime }}</span>
      </div>
      <details class="trace-group" open>
        <summary class="trace-caption">
          <span class="trace-caption-copy">
            <strong>{{ traceTitle }}</strong>
            <span>{{ t('tool.traceCount', { count: executions.length }) }}</span>
          </span>
          <span class="trace-chevron" aria-hidden="true">⌄</span>
        </summary>
        <ToolExecutionChain
          :executions="executions"
          :workspace-context="workspaceContext"
        />
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolExecutionChain from '@/components/chat/ToolExecutionChain.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import { useI18n } from '@/composables/useI18n'
import type { TranscriptItem, ToolExecutionMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { conversationVisibleParts } from '@/utils/toolPresentation'

const props = withDefaults(defineProps<{
  messages: TranscriptItem[]
  workspaceContext?: WorkspaceRequestContext | null
  embedded?: boolean
}>(), {
  workspaceContext: null,
  embedded: false,
})

const { locale, t } = useI18n()
const executions = computed<ToolExecutionMessagePart[]>(() => props.messages.flatMap(message => (
  conversationVisibleParts(message.parts).filter(
    (part): part is ToolExecutionMessagePart => part.type === 'tool_execution',
  )
)).map((part, sourceIndex) => ({ part, sourceIndex })).sort((left, right) => {
  const leftCompleted = Date.parse(String(left.part.completedAt || ''))
  const rightCompleted = Date.parse(String(right.part.completedAt || ''))
  const leftHasCompleted = Number.isFinite(leftCompleted)
  const rightHasCompleted = Number.isFinite(rightCompleted)
  if (leftHasCompleted && rightHasCompleted && leftCompleted !== rightCompleted) {
    return leftCompleted - rightCompleted
  }
  if (leftHasCompleted !== rightHasCompleted) return leftHasCompleted ? -1 : 1
  return left.sourceIndex - right.sourceIndex
}).map(item => item.part))
const groupState = computed(() => {
  if (executions.value.some(item => item.status === 'awaiting_approval')) return 'approval'
  if (executions.value.some(item => item.error || item.status === 'failed')) return 'failed'
  if (executions.value.some(item => item.status === 'cancelled' || item.status === 'stopped')) return 'cancelled'
  if (executions.value.some(item => ['requested', 'running', 'streaming'].includes(String(item.status || '')))) return 'running'
  return 'completed'
})
const traceTitle = computed(() => t(`tool.trace.${groupState.value}` as any))
const formattedTime = computed(() => new Date(props.messages[0]?.timestamp || Date.now()).toLocaleTimeString(locale.value, {
  hour: '2-digit',
  minute: '2-digit',
}))

</script>

<style scoped>
.tool-trace-message {
  display: flex;
  gap: var(--app-space-md);
  padding: 8px var(--app-space-md);
}

.tool-trace-message.embedded {
  padding: 0 0 12px;
}

.assistant-avatar {
  display: grid;
  width: 40px;
  height: 36px;
  flex: 0 0 40px;
  place-items: center;
}

.trace-content {
  min-width: 0;
  flex: 1;
}

.trace-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin: 0 0 5px;
  font-size: 13px;
}

.trace-header strong {
  font-family: 'Avenir Next', 'SF Pro Display', 'Arial Rounded MT Bold', sans-serif;
  font-size: 16px;
  font-weight: 780;
  letter-spacing: -.055em;
}

.trace-header span {
  color: var(--app-text-muted);
  font-size: 11px;
}

.trace-caption {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  margin-bottom: 5px;
  padding: 3px 0;
  color: var(--app-text-muted);
  font-size: 11px;
  cursor: pointer;
  list-style: none;
}

.trace-caption::-webkit-details-marker { display: none; }

.trace-caption-copy {
  grid-column: 2;
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.trace-caption-copy strong {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.trace-chevron {
  grid-column: 3;
  justify-self: end;
  transition: transform 160ms ease;
}

.trace-group[open] .trace-chevron {
  transform: rotate(180deg);
}

</style>
