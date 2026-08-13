<template>
  <div class="tool-trace-message">
    <div class="assistant-avatar" aria-hidden="true">A</div>
    <div class="trace-content">
      <div class="trace-header">
        <strong>{{ t('roles.assistant') }}</strong>
        <span>{{ formattedTime }}</span>
      </div>
      <div class="trace-caption">
        <strong>{{ traceTitle }}</strong>
        <span>{{ t('tool.traceCount', { count: executions.length }) }}</span>
      </div>
      <div class="tool-trace" :class="`trace-state-${groupState}`">
        <div
          v-for="(execution, index) in executions"
          :key="execution.id"
          class="trace-node"
          :class="`node-state-${executionState(execution)}`"
        >
          <span class="node-rail" aria-hidden="true">
            <span class="node-dot"></span>
            <span v-if="index < executions.length - 1" class="node-line"></span>
          </span>
          <ToolExecutionCard
            :part="execution"
            :workspace-context="workspaceContext"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ToolExecutionCard from '@/components/chat/ToolExecutionCard.vue'
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

function executionState(execution: ToolExecutionMessagePart): string {
  if (execution.status === 'awaiting_approval') return 'approval'
  if (execution.error || execution.status === 'failed') return 'failed'
  if (execution.status === 'cancelled' || execution.status === 'stopped') return 'cancelled'
  if (['requested', 'running', 'streaming'].includes(String(execution.status || ''))) return 'running'
  return 'completed'
}
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
  align-items: baseline;
  gap: 7px;
  margin-bottom: 5px;
  color: var(--app-text-muted);
  font-size: 11px;
}

.trace-caption strong {
  color: var(--app-text-secondary);
  font-size: 12px;
}

.tool-trace {
  display: grid;
}

.trace-node {
  position: relative;
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr);
  min-width: 0;
}

.node-rail {
  position: relative;
  display: flex;
  justify-content: center;
}

.node-dot {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  margin-top: 16px;
  border: 2px solid var(--app-surface);
  border-radius: 50%;
  background: var(--app-success);
  box-shadow: 0 0 0 1px var(--app-border-hover);
}

.node-line {
  position: absolute;
  top: 24px;
  bottom: -16px;
  width: 1px;
  background: var(--app-border-hover);
}

.node-state-running .node-dot { background: var(--app-info); animation: app-pulse-soft 1.4s ease-in-out infinite; }
.node-state-approval .node-dot { background: var(--app-warning); }
.node-state-failed .node-dot { background: var(--app-error); }
.node-state-cancelled .node-dot { background: var(--app-text-muted); }

.trace-node :deep(.tool-execution-card) {
  margin-bottom: 5px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  box-shadow: none;
}

.trace-node :deep(.tool-summary) {
  min-height: 40px;
  padding: 5px 7px;
}

.trace-node :deep(.tool-body) {
  margin: 0 7px 8px;
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-sm);
}
</style>
