<template>
  <n-popover
    ref="popoverRef"
    v-if="visibleTasks.length && primaryTask"
    trigger="click"
    :show="expanded"
    :placement="side === 'left' ? 'bottom-start' : 'bottom-end'"
    :flip="false"
    :show-arrow="false"
    raw
    @update:show="expanded = $event"
  >
    <template #trigger>
      <button
        class="task-stack-summary"
        :class="{ 'has-multiple': visibleTasks.length > 1, 'requires-action': requiresAction }"
        type="button"
        :aria-expanded="expanded"
      >
        <span class="task-stack-mark" :class="{ 'is-active': hasActiveTasks }" aria-hidden="true">
          <SubAgentMascot
            :status="primaryTask.status"
            :task-id="primaryTask.task_id"
            :awaiting-input="primaryRequiresAction"
            :size="40"
          />
        </span>
        <span class="task-stack-copy">
          <span class="task-stack-meta">
            <strong>{{ primaryAgentName }}</strong>
            <small>{{ elapsedLabel }}</small>
          </span>
          <span class="task-stack-summary-text">{{ currentActivitySummary }}</span>
        </span>
        <span v-if="visibleTasks.length > 1" class="task-stack-count">+{{ visibleTasks.length - 1 }}</span>
        <span class="task-stack-chevron" aria-hidden="true">⌄</span>
      </button>
    </template>

    <section class="task-stack-popover" :class="`dock-side-${side}`">
      <header class="stack-popover-header">
        <div>
          <strong>{{ t('backgroundTask.stackTitle') }}</strong>
          <small>{{ t('backgroundTask.stackCount', { count: visibleTasks.length }) }}</small>
        </div>
        <button type="button" :aria-label="t('common.close')" @click="expanded = false">×</button>
      </header>
      <div class="task-stack-list">
        <BackgroundTaskCard
          v-for="task in visibleTasks"
          :key="task.task_id"
          :task="task"
          @updated="reconcileOne"
          @deleted="removeTask"
        />
      </div>
    </section>
  </n-popover>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NPopover } from 'naive-ui'
import { backgroundTasksApi, type BackgroundTask } from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskCard from './BackgroundTaskCard.vue'
import SubAgentMascot from '@/components/brand/SubAgentMascot.vue'

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
const popoverRef = ref<{ syncPosition: () => void } | null>(null)
const tasks = ref<BackgroundTask[]>([])
const expanded = ref(false)
let pollTimer: number | null = null
let elapsedTimer: number | null = null
let requestVersion = 0
let refreshInFlight = false
let refreshQueued = false
const currentTime = ref(Date.now())

defineExpose({ syncPosition })

const visibleTasks = computed(() => {
  const active = tasks.value.filter(task => !isTerminal(task.status)).sort(compareNewest)
  const completed = tasks.value
    .filter(task => isTerminal(task.status))
    .sort(compareNewest)
  return [...active, ...completed]
})
const primaryTask = computed(() => visibleTasks.value[0] || null)
const hasActiveTasks = computed(() => visibleTasks.value.some(task => !isTerminal(task.status)))
const requiresAction = computed(() => visibleTasks.value.some(task => (
  task.pending_interaction?.kind === 'tool_approval'
  || task.pending_interaction?.kind === 'ask_user'
  || task.pending_interaction?.kind === 'resource_request'
)))
const primaryRequiresAction = computed(() => {
  const kind = primaryTask.value?.pending_interaction?.kind
  return kind === 'tool_approval' || kind === 'ask_user' || kind === 'resource_request'
})
const capsuleStatus = computed(() => {
  const task = primaryTask.value
  if (!task) return ''
  return task.pending_interaction?.kind === 'tool_approval'
    ? t('backgroundTask.capsule.approval')
    : task.pending_interaction?.kind === 'ask_user' || task.pending_interaction?.kind === 'resource_request'
      ? t('backgroundTask.capsule.answer')
      : taskTypeLabel(task.status)
})
const primaryAgentName = computed(() => String(
  primaryTask.value?.agent_name || t('backgroundTask.memberFallback'),
))
const currentActivitySummary = computed(() => {
  const task = primaryTask.value
  if (!task) return t('backgroundTask.stackTitle')
  if (task.pending_interaction?.kind === 'tool_approval') {
    return task.pending_interaction.message || t('backgroundTask.pendingApproval')
  }
  if (task.pending_interaction?.kind === 'ask_user' || task.pending_interaction?.kind === 'resource_request') {
    return task.pending_interaction.message || t('backgroundTask.pendingInput')
  }
  if (task.status === 'failed') return task.error?.message || t('backgroundTask.failedFallback')
  if (task.status === 'succeeded' && task.result_summary) return task.result_summary
  return task.activity_summary || task.task_text || capsuleStatus.value
})
const elapsedLabel = computed(() => {
  const task = primaryTask.value
  if (!task) return ''
  const terminal = isTerminal(task.status)
  const duration = formatDuration(task.started_at || task.created_at, terminal ? task.completed_at || task.updated_at : null)
  return t(terminal ? 'backgroundTask.finishedIn' : 'backgroundTask.processedFor', { duration })
})

watch(requiresAction, (next, previous) => {
  if (next && !previous) expanded.value = true
})

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
  stopElapsedClock()
  window.removeEventListener('fastagentfactory:background-task-updated', handleTaskEvent)
})

onMounted(() => {
  window.addEventListener('fastagentfactory:background-task-updated', handleTaskEvent)
  elapsedTimer = window.setInterval(() => { currentTime.value = Date.now() }, 1000)
})

async function refreshTasks(version: number) {
  const sessionId = String(props.sessionId || '').trim()
  if (!sessionId) return
  if (refreshInFlight) {
    refreshQueued = true
    return
  }
  refreshInFlight = true
  try {
    const response = await backgroundTasksApi.list({ sessionId })
    if (version !== requestVersion || sessionId !== String(props.sessionId || '').trim()) return
    tasks.value.splice(0, tasks.value.length, ...response.tasks)
  } catch (error) {
    console.warn('Failed to refresh background tasks:', error)
  } finally {
    refreshInFlight = false
    if (refreshQueued) {
      refreshQueued = false
      scheduleRefresh(requestVersion, 0)
    } else if (version === requestVersion) {
      scheduleRefresh(version, 2000)
    }
  }
}

function reconcileOne(updated: BackgroundTask) {
  const index = tasks.value.findIndex(task => task.task_id === updated.task_id)
  if (index >= 0) tasks.value.splice(index, 1, updated)
}

function removeTask(taskId: string) {
  const index = tasks.value.findIndex(task => task.task_id === taskId)
  if (index >= 0) tasks.value.splice(index, 1)
}

function stopPolling() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
  refreshQueued = false
}

function stopElapsedClock() {
  if (elapsedTimer !== null) window.clearInterval(elapsedTimer)
  elapsedTimer = null
}

function scheduleRefresh(version: number, delay: number) {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = window.setTimeout(() => {
    pollTimer = null
    void refreshTasks(version)
  }, delay)
}

function handleTaskEvent(event: Event) {
  const updatedSessionId = String(
    (event as CustomEvent<{ session_id?: string | null }>).detail?.session_id || '',
  ).trim()
  const activeSessionId = String(props.sessionId || '').trim()
  if (updatedSessionId && updatedSessionId !== activeSessionId) return
  scheduleRefresh(requestVersion, 50)
}

function syncPosition() {
  popoverRef.value?.syncPosition()
}

function isTerminal(status: BackgroundTask['status']): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

function compareNewest(left: BackgroundTask, right: BackgroundTask): number {
  return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
}

function taskTypeLabel(status: BackgroundTask['status']): string {
  if (status === 'queued') return t('backgroundTask.capsule.queued')
  if (status === 'succeeded') return t('backgroundTask.capsule.completed')
  if (status === 'failed') return t('backgroundTask.capsule.failed')
  if (status === 'cancelled' || status === 'cancelling') return t('backgroundTask.capsule.stopping')
  return t('backgroundTask.capsule.delegating')
}

function formatDuration(startValue: string, endValue: string | null): string {
  const start = Date.parse(startValue)
  const end = endValue ? Date.parse(endValue) : currentTime.value
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    return t('backgroundTask.duration.seconds', { count: 0 })
  }
  const totalSeconds = Math.max(0, Math.floor((end - start) / 1000))
  if (totalSeconds < 60) return t('backgroundTask.duration.seconds', { count: totalSeconds })
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) {
    return seconds
      ? t('backgroundTask.duration.minutesSeconds', { minutes, seconds })
      : t('backgroundTask.duration.minutes', { count: minutes })
  }
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes
    ? t('backgroundTask.duration.hoursMinutes', { hours, minutes: remainingMinutes })
    : t('backgroundTask.duration.hours', { count: hours })
}
</script>

<style scoped>
.task-stack-summary { width: min(360px, calc(100vw - 48px)); min-height: 72px; display: flex; align-items: center; gap: 10px; padding: 10px 12px 10px 9px; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 18px; box-shadow: 0 10px 28px color-mix(in srgb, var(--app-text) 11%, transparent); cursor: pointer; transition: transform .2s cubic-bezier(.16, 1, .3, 1), border-color .2s ease, box-shadow .2s ease; }
.task-stack-summary:hover { transform: translateY(-1px); border-color: var(--app-border-hover); box-shadow: 0 14px 34px color-mix(in srgb, var(--app-text) 14%, transparent); }
.task-stack-summary.requires-action { border-color: var(--app-text); }
.task-stack-mark { width: 42px; height: 42px; flex: 0 0 auto; display: grid; overflow: hidden; place-items: center; border-radius: 12px; background: var(--app-surface-muted); }
.task-stack-copy { min-width: 0; flex: 1; display: grid; gap: 6px; text-align: left; }
.task-stack-meta { min-width: 0; display: flex; align-items: baseline; gap: 7px; color: var(--app-text-muted); }
.task-stack-meta strong, .task-stack-meta small, .task-stack-summary-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-stack-meta strong { color: var(--app-text); font-size: 12px; font-weight: 620; }
.task-stack-meta small { font-size: 10px; }
.task-stack-summary-text { padding-top: 6px; border-top: 1px solid var(--app-divider); color: var(--app-text-secondary); font-size: 11px; line-height: 1.35; }
.task-stack-count { flex: 0 0 auto; display: grid; min-width: 25px; height: 25px; place-items: center; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text-secondary); font-size: 10px; }
.task-stack-chevron { color: var(--app-text-muted); font-size: 11px; }
.task-stack-popover { width: min(480px, calc(100vw - 32px)); max-height: min(72vh, 680px); overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr); color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 18px; box-shadow: 0 28px 80px color-mix(in srgb, var(--app-text) 18%, transparent); animation: task-popover-in .24s cubic-bezier(.16, 1, .3, 1) both; }
.stack-popover-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--app-divider); }
.stack-popover-header > div { display: flex; align-items: baseline; gap: 8px; }
.stack-popover-header strong { font-size: 13px; }
.stack-popover-header small { color: var(--app-text-muted); font-size: 11px; }
.stack-popover-header button { width: 28px; height: 28px; border: 0; border-radius: 50%; color: var(--app-text); background: transparent; font-size: 18px; cursor: pointer; }
.stack-popover-header button:hover { background: var(--app-surface-hover); }
.task-stack-list { overflow-y: auto; }
.task-stack-list :deep(.background-task-card + .background-task-card) { border-top: 1px solid var(--app-divider); }
@keyframes task-popover-in { from { opacity: 0; transform: translateY(-7px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
</style>
