<template>
  <div class="tool-execution-chain">
    <div
      v-for="(execution, index) in executions"
      :key="execution.id"
      class="chain-node"
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
</template>

<script setup lang="ts">
import ToolExecutionCard from '@/components/chat/ToolExecutionCard.vue'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import type { ToolExecutionMessagePart } from '@/types/protocol'

withDefaults(defineProps<{
  executions: ToolExecutionMessagePart[]
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  workspaceContext: null,
})

function executionState(execution: ToolExecutionMessagePart): string {
  if (execution.status === 'awaiting_approval') return 'approval'
  if (execution.error || execution.status === 'failed') return 'failed'
  if (execution.status === 'cancelled' || execution.status === 'stopped') return 'cancelled'
  if (['requested', 'running', 'streaming'].includes(String(execution.status || ''))) return 'running'
  return 'completed'
}
</script>

<style scoped>
.tool-execution-chain { display: grid; }
.chain-node { position: relative; display: grid; grid-template-columns: 22px minmax(0, 1fr); min-width: 0; }
.node-rail { position: relative; display: flex; justify-content: center; }
.node-dot { position: relative; z-index: 1; width: 9px; height: 9px; margin-top: 16px; border: 2px solid var(--app-surface); border-radius: 50%; background: var(--app-success); box-shadow: 0 0 0 1px var(--app-border-hover); }
.node-line { position: absolute; top: 24px; bottom: -16px; width: 1px; background: var(--app-border-hover); }
.node-state-running .node-dot { background: var(--app-info); animation: app-pulse-soft 1.4s ease-in-out infinite; }
.node-state-approval .node-dot { background: var(--app-warning); }
.node-state-failed .node-dot { background: var(--app-error); }
.node-state-cancelled .node-dot { background: var(--app-text-muted); }
.chain-node :deep(.tool-execution-card) { margin-bottom: 5px; border: 0; border-radius: var(--app-radius-sm); background: transparent; box-shadow: none; }
.chain-node :deep(.tool-summary) { min-height: 40px; padding: 5px 7px; }
.chain-node :deep(.tool-body) { margin: 0 7px 8px; border: 1px solid var(--app-divider); border-radius: var(--app-radius-sm); }
</style>
