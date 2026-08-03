<template>
  <section
    v-if="visibleTasks.length && primaryTask"
    class="background-task-stack"
    :class="[
      { 'is-expanded': expanded, 'has-multiple': visibleTasks.length > 1, 'is-compact': compact },
      `dock-side-${side}`,
    ]"
    aria-live="polite"
  >
    <button
      class="task-stack-summary"
      type="button"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <span class="task-stack-mark" :class="{ 'is-active': hasActiveTasks }" aria-hidden="true">
        <span v-if="hasActiveTasks" class="task-stack-spinner"></span>
        <span v-else>✓</span>
      </span>
      <span class="task-stack-copy">
        <strong v-if="!compact">{{ primaryTask.task_text || t('backgroundTask.stackTitle') }}</strong>
        <strong v-else>{{ t('backgroundTask.stackCount', { count: visibleTasks.length }) }}</strong>
        <small v-if="!compact">{{ primaryStatusLabel }} · {{ t('backgroundTask.stackCount', { count: visibleTasks.length }) }}</small>
        <small v-else>{{ primaryStatusLabel }}</small>
      </span>
      <span class="task-stack-chevron" aria-hidden="true">⌄</span>
    </button>
    <div v-if="expanded" class="task-stack-list">
      <BackgroundTaskCard
        v-for="task in visibleTasks"
        :key="task.task_id"
        :task="task"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { backgroundTasksApi, type BackgroundTask } from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskCard from './BackgroundTaskCard.vue'

const props = withDefaults(defineProps<{
  sessionId?: string | null
  compact?: boolean
  side?: 'left' | 'right'
}>(), {
  sessionId: null,
  compact: false,
  side: 'left',
})

const { t } = useI18n()
const tasks = ref<BackgroundTask[]>([])
const expanded = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let requestVersion = 0

const visibleTasks = computed(() => {
  const active = tasks.value.filter(task => !isTerminal(task.status))
  const completed = tasks.value
    .filter(task => isTerminal(task.status))
    .sort(compareNewest)
    .slice(0, 3)
  return [...active.sort(compareNewest), ...completed]
})
const primaryTask = computed(() => visibleTasks.value[0] || null)
const hasActiveTasks = computed(() => visibleTasks.value.some(task => !isTerminal(task.status)))
const primaryStatusLabel = computed(() => (
  primaryTask.value
    ? t(`backgroundTask.status.${primaryTask.value.status}` as any)
    : ''
))

watch(
  () => visibleTasks.value.some(task => task.status === 'waiting_approval' || task.status === 'waiting_external'),
  requiresAction => {
    if (requiresAction) expanded.value = true
  },
)

watch(
  () => props.sessionId,
  () => {
    requestVersion += 1
    stopPolling()
    tasks.value = []
    expanded.value = false
    void refreshTasks(requestVersion)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  requestVersion += 1
  stopPolling()
})

async function refreshTasks(version: number) {
  const sessionId = String(props.sessionId || '').trim()
  if (!sessionId) return
  try {
    const response = await backgroundTasksApi.list({ sessionId })
    if (version !== requestVersion || sessionId !== String(props.sessionId || '').trim()) return
    reconcileTasks(response.tasks)
  } catch (error) {
    console.warn('Failed to refresh background tasks:', error)
  } finally {
    if (version === requestVersion) {
      pollTimer = setTimeout(() => void refreshTasks(version), 2000)
    }
  }
}

function reconcileTasks(incoming: BackgroundTask[]) {
  tasks.value.splice(0, tasks.value.length, ...incoming)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function isTerminal(status: BackgroundTask['status']): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

function compareNewest(left: BackgroundTask, right: BackgroundTask): number {
  return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
}
</script>

<style scoped>
.background-task-stack {
  position: relative;
  z-index: 3;
  margin: 12px var(--app-space-md) 0;
  isolation: isolate;
}

.background-task-stack.is-compact {
  width: max-content;
  max-width: 190px;
  margin: 0;
}

.is-compact .task-stack-summary {
  min-height: 40px;
  padding: 5px 12px 5px 7px;
  border-radius: 999px;
  box-shadow: 0 8px 24px color-mix(in srgb, var(--app-text) 10%, transparent);
}

.is-compact .task-stack-mark {
  width: 28px;
  height: 28px;
  border-radius: 50%;
}

.is-compact .task-stack-copy { display: flex; align-items: baseline; gap: 5px; }
.is-compact .task-stack-copy strong { font-size: 11px; }
.is-compact .task-stack-copy small { font-size: 9px; }
.is-compact .task-stack-chevron { font-size: 10px; }

.is-compact .task-stack-list {
  position: absolute;
  bottom: 0;
  width: min(430px, calc(100vw - 48px));
  max-height: min(66vh, 560px);
  border: 1px solid var(--app-border);
  border-radius: 18px;
  box-shadow: 0 24px 64px color-mix(in srgb, var(--app-text) 16%, transparent);
  transform-origin: bottom left;
  animation: task-panel-in .24s cubic-bezier(.16, 1, .3, 1) both;
}

.is-compact.dock-side-left .task-stack-list { left: calc(100% + 10px); }
.is-compact.dock-side-right .task-stack-list { right: calc(100% + 10px); transform-origin: bottom right; }

.background-task-stack.has-multiple:not(.is-expanded)::before,
.background-task-stack.has-multiple:not(.is-expanded)::after {
  content: '';
  position: absolute;
  z-index: -1;
  left: 18px;
  right: 18px;
  height: 18px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg) var(--app-radius-lg) 0 0;
  background: var(--app-surface);
}

.background-task-stack.has-multiple:not(.is-expanded)::before {
  top: -6px;
  opacity: 0.72;
}

.background-task-stack.has-multiple:not(.is-expanded)::after {
  top: -11px;
  left: 34px;
  right: 34px;
  opacity: 0.42;
}

.task-stack-summary {
  width: 100%;
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  text-align: left;
  box-shadow: var(--app-shadow-md);
  cursor: pointer;
  transition: border-color var(--app-transition-fast), transform var(--app-transition-fast);
}

.task-stack-summary:hover {
  border-color: var(--app-border-hover);
}

.task-stack-summary:active {
  transform: scale(0.995);
}

.is-expanded .task-stack-summary {
  border-radius: var(--app-radius-lg) var(--app-radius-lg) 0 0;
  box-shadow: none;
}

.task-stack-mark {
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  font-size: 14px;
  font-weight: 700;
}

.task-stack-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--app-divider);
  border-top-color: var(--app-text);
  border-radius: 50%;
  animation: task-stack-spin 0.9s linear infinite;
}

.task-stack-copy {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 3px;
}

.task-stack-copy strong,
.task-stack-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-stack-copy strong {
  font-size: 13px;
}

.task-stack-copy small {
  color: var(--app-text-muted);
  font-size: 12px;
}

.task-stack-chevron {
  flex: 0 0 auto;
  color: var(--app-text-muted);
  transition: transform var(--app-transition-base);
}

.is-expanded .task-stack-chevron {
  transform: rotate(180deg);
}

.task-stack-list {
  max-height: min(38vh, 360px);
  overflow-y: auto;
  padding: 0;
  border: 1px solid var(--app-border);
  border-top: 0;
  border-radius: 0 0 var(--app-radius-lg) var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-md);
}

.task-stack-list :deep(.background-task-card) {
  margin: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.task-stack-list :deep(.background-task-card + .background-task-card) {
  border-top: 1px solid var(--app-divider);
}

@keyframes task-stack-spin {
  to { transform: rotate(360deg); }
}

@keyframes task-panel-in {
  from { opacity: 0; transform: translateY(8px) scale(.97); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
</style>
