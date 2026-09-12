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
        variant="activity"
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
.chain-node { position: relative; display: grid; grid-template-columns: 18px minmax(0, 1fr); min-width: 0; }
.node-rail { position: relative; display: flex; justify-content: center; }
/*
 * 完成态用中性色：每一行都点一个绿点只会给活动流加噪音，
 * 只有进行中 / 等待确认 / 失败才需要颜色。
 */
.node-dot { position: relative; z-index: 1; width: 8px; height: 8px; margin-top: 14px; border: 2px solid var(--app-surface); border-radius: 50%; background: var(--app-text-muted); box-shadow: 0 0 0 1px var(--app-border-hover); }
.node-line { position: absolute; top: 21px; bottom: -11px; width: 1px; background: var(--app-border-hover); }
.node-state-running .node-dot { background: var(--app-info); animation: app-pulse-soft 1.4s ease-in-out infinite; }
.node-state-approval .node-dot { background: var(--app-warning); }
.node-state-failed .node-dot { background: var(--app-error); }
.node-state-cancelled .node-dot { background: var(--app-text-muted); }
.chain-node :deep(.tool-execution-card) { margin-bottom: 2px; border: 0; border-radius: var(--app-radius-sm); background: transparent; box-shadow: none; }
.chain-node :deep(.tool-summary) { min-height: 34px; padding: 4px 6px; }
.chain-node :deep(.tool-body) { margin: 0 6px 6px; border: 1px solid var(--app-divider); border-radius: var(--app-radius-sm); }
</style>
