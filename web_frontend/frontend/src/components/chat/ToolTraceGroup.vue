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
      <details
        class="trace-group"
        :class="`trace-state-${traceState}`"
        :open="expanded"
        @toggle="handleToggle"
      >
        <summary class="trace-caption">
          <span class="trace-caption-copy">
            <span class="trace-state-dot" aria-hidden="true"></span>
            <span v-if="toolKinds.visible.length" class="trace-kinds" aria-hidden="true">
              <span
                v-for="kind in toolKinds.visible"
                :key="kind.icon"
                class="trace-kind"
                :title="kind.label"
              >
                <ToolIcon :name="kind.icon" :size="12" />
              </span>
              <span v-if="toolKinds.overflow" class="trace-kind-overflow">+{{ toolKinds.overflow }}</span>
            </span>
            <span class="trace-count">{{ t('tool.traceCount', { count: summary.count }) }}</span>
            <span v-if="summary.changedFileCount" class="trace-meta">
              {{ t('tool.traceFiles', { count: summary.changedFileCount }) }}
            </span>
            <span
              v-if="summary.failureCount"
              class="trace-meta trace-meta-failed"
            >{{ t('tool.traceFailures', { count: summary.failureCount }) }}</span>
            <span v-if="durationLabel" class="trace-meta trace-duration">{{ durationLabel }}</span>
          </span>
          <span class="trace-side">
            <span v-if="traceState === 'running'" class="trace-live">
              {{ t('tool.traceRunning') }}
            </span>
            <span class="trace-chevron" aria-hidden="true">⌄</span>
          </span>
        </summary>
        <ToolExecutionChain
          v-if="expanded"
          class="trace-body"
          :executions="props.executions"
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
import ToolIcon from '@/components/common/ToolIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAutoExpandedDetails } from '@/composables/useAutoExpandedDetails'
import type { ToolExecutionMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import {
  formatToolTraceDuration,
  isToolExecutionFailed,
  isToolExecutionRunning,
  toolTraceSummary,
} from '@/utils/toolTraceSummary'
import { toolPresentation, type ToolIconName } from '@/utils/toolPresentation'

const props = withDefaults(defineProps<{
  executions: ToolExecutionMessagePart[]
  timestamp?: string
  workspaceContext?: WorkspaceRequestContext | null
  embedded?: boolean
}>(), {
  timestamp: '',
  workspaceContext: null,
  embedded: false,
})

const { locale, t } = useI18n()
const formattedTime = computed(() => new Date(props.timestamp || Date.now()).toLocaleTimeString(locale.value, {
  hour: '2-digit',
  minute: '2-digit',
}))

const summary = computed(() => toolTraceSummary(props.executions))
const runningCount = computed(() => props.executions.filter(isToolExecutionRunning).length)
const isActive = computed(() => runningCount.value > 0)
const hasFailure = computed(() => props.executions.some(isToolExecutionFailed))
const traceState = computed(() => {
  if (isActive.value) return 'running'
  if (hasFailure.value) return 'failed'
  return 'completed'
})
const durationLabel = computed(() => (
  summary.value.durationMs == null ? '' : formatToolTraceDuration(summary.value.durationMs)
))

// A collapsed row that only says "executed 9 tools" still forces the reader to
// open it to learn what happened. A short strip of the distinct tool kinds lets
// a finished group be scanned without expanding anything.
const MAX_KIND_ICONS = 4
const toolKinds = computed(() => {
  const seen = new Map<string, { icon: ToolIconName; label: string }>()
  props.executions.forEach((execution) => {
    const presentation = toolPresentation(execution.toolName, execution.arguments)
    if (seen.has(presentation.icon)) return
    seen.set(presentation.icon, {
      icon: presentation.icon,
      label: presentation.labelKey ? t(presentation.labelKey as any) : execution.toolName,
    })
  })
  const kinds = [...seen.values()]
  return {
    visible: kinds.slice(0, MAX_KIND_ICONS),
    overflow: Math.max(0, kinds.length - MAX_KIND_ICONS),
  }
})

// A long task can produce dozens of groups; keeping every historical group
// expanded is what made transcripts unreadable. Groups therefore expand while
// they are live, keep themselves open when something failed, and otherwise rest
// collapsed. An explicit user toggle always wins until the group's activity
// state changes again.
const autoExpanded = computed(() => isActive.value || hasFailure.value)
const { expanded, handleToggle } = useAutoExpandedDetails(autoExpanded)
</script>

<style scoped>
.tool-trace-message {
  display: flex;
  gap: var(--app-space-md);
  padding: 8px var(--app-space-md);
}

.tool-trace-message.embedded {
  padding: 0;
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
  display: flex;
  width: 100%;
  min-height: 27px;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 1px 0;
  padding: 3px 10px 3px 8px;
  border: 1px solid transparent;
  border-radius: var(--app-radius-pill);
  color: var(--app-text-muted);
  font-size: 12px;
  cursor: pointer;
  list-style: none;
  transition: background-color var(--app-transition-base), border-color var(--app-transition-base), color var(--app-transition-base);
}

.trace-caption:hover {
  border-color: var(--app-border);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
}

.trace-group[open] > .trace-caption {
  border-color: color-mix(in srgb, var(--app-info) 24%, var(--app-border));
  background: color-mix(in srgb, var(--app-info) 6%, var(--app-surface-muted));
  color: var(--app-text-secondary);
}

.trace-caption::-webkit-details-marker { display: none; }

.trace-caption-copy {
  display: flex;
  min-width: 0;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0 8px;
}

.trace-count { font-weight: 550; letter-spacing: -0.01em; }

.trace-kinds {
  display: inline-flex;
  align-self: center;
  align-items: center;
  gap: 3px;
}

.trace-kind {
  display: grid;
  width: 19px;
  height: 19px;
  place-items: center;
  border-radius: var(--app-radius-sm);
  background: color-mix(in srgb, var(--app-text) 6%, transparent);
  color: var(--app-text-muted);
}

.trace-kind-overflow {
  color: var(--app-text-subtle);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

.trace-state-dot {
  align-self: center;
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: var(--app-success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-success) 15%, transparent);
}

.trace-state-running .trace-state-dot {
  background: var(--app-info);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-info) 15%, transparent);
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.trace-state-failed .trace-state-dot {
  background: var(--app-error);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-error) 15%, transparent);
}

.trace-meta::before {
  margin-right: 7px;
  color: var(--app-text-subtle);
  content: '·';
}

.trace-meta-failed { color: var(--app-error); }

.trace-duration { font-variant-numeric: tabular-nums; }

.trace-side {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 7px;
}

.trace-live { color: var(--app-info); }

.trace-chevron {
  flex: 0 0 auto;
  color: var(--app-text-subtle);
  font-size: 13px;
  line-height: 1;
  transition: transform var(--app-transition-base), color var(--app-transition-base);
}

.trace-caption:hover .trace-chevron { color: var(--app-text-secondary); }

.trace-group[open] .trace-chevron {
  transform: rotate(180deg);
}

/* Expanded tool cards sit slightly inset from the collapsed caption they belong to. */
.trace-body { padding: 3px 0 4px 6px; }
</style>
