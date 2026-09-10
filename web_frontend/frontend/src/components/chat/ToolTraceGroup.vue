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
          :executions="props.executions"
          :workspace-context="workspaceContext"
        />
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ToolExecutionChain from '@/components/chat/ToolExecutionChain.vue'
import ComboFrameAnimation from '@/components/brand/ComboFrameAnimation.vue'
import { useI18n } from '@/composables/useI18n'
import type { ToolExecutionMessagePart } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import {
  formatToolTraceDuration,
  isToolExecutionFailed,
  isToolExecutionRunning,
  toolTraceSummary,
} from '@/utils/toolTraceSummary'

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

// A long task can produce dozens of groups; keeping every historical group
// expanded is what made transcripts unreadable. Groups therefore expand while
// they are live, keep themselves open when something failed, and otherwise rest
// collapsed. An explicit user toggle always wins until the group's activity
// state changes again.
const autoExpanded = computed(() => isActive.value || hasFailure.value)
const userOverride = ref<boolean | null>(null)
const expanded = computed(() => userOverride.value ?? autoExpanded.value)

watch(autoExpanded, () => {
  userOverride.value = null
})

function handleToggle(event: Event) {
  const element = (event.currentTarget || event.target) as HTMLDetailsElement | null
  if (!element || element.open === expanded.value) return
  userOverride.value = element.open
}
</script>

<style scoped>
.tool-trace-message {
  display: flex;
  gap: var(--app-space-md);
  padding: 8px var(--app-space-md);
}

.tool-trace-message.embedded {
  padding: 0 0 3px;
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
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 2px;
  padding: 3px 6px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text-muted);
  font-size: 11px;
  cursor: pointer;
  list-style: none;
  transition: background-color var(--app-transition-base), color var(--app-transition-base);
}

.trace-caption:hover {
  background: var(--app-surface-hover);
  color: var(--app-text-secondary);
}

.trace-caption::-webkit-details-marker { display: none; }

.trace-caption-copy {
  display: flex;
  min-width: 0;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 0 7px;
}

.trace-state-dot {
  align-self: center;
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  background: var(--app-success);
}

.trace-state-running .trace-state-dot {
  background: var(--app-info);
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.trace-state-failed .trace-state-dot {
  background: var(--app-error);
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
  transition: transform 160ms ease;
}

.trace-group[open] .trace-chevron {
  transform: rotate(180deg);
}
</style>
