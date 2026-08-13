<template>
  <div class="tool-trace-message">
    <div class="assistant-avatar" aria-hidden="true">A</div>
    <div class="trace-content">
      <div class="trace-header">
        <strong>{{ t('roles.assistant') }}</strong>
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
import { useI18n } from '@/composables/useI18n'
import type { TranscriptItem, ToolExecutionMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { conversationVisibleParts } from '@/utils/toolPresentation'

const props = withDefaults(defineProps<{
  messages: TranscriptItem[]
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  workspaceContext: null,
})

const { locale, t } = useI18n()
const executions = computed<ToolExecutionMessagePart[]>(() => props.messages.flatMap(message => (
  conversationVisibleParts(message.parts).filter(
    (part): part is ToolExecutionMessagePart => part.type === 'tool_execution',
  )
)))
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

.assistant-avatar {
  display: grid;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  place-items: center;
  border: 1px solid var(--app-text);
  border-radius: 50%;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: 14px;
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

.trace-header span {
  color: var(--app-text-muted);
  font-size: 11px;
}

.trace-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 5px;
  padding: 3px 0;
  color: var(--app-text-muted);
  font-size: 11px;
  cursor: pointer;
  list-style: none;
}

.trace-caption::-webkit-details-marker { display: none; }

.trace-caption-copy {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.trace-caption-copy strong {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.trace-chevron {
  transition: transform 160ms ease;
}

.trace-group[open] .trace-chevron {
  transform: rotate(180deg);
}

</style>
