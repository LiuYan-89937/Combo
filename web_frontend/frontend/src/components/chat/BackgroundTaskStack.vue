<template>
  <div v-if="visibleTasks.length" ref="layerRef" class="task-capsule-layer">
    <div
      v-for="(task, index) in visibleTasks"
      :key="task.task_id"
      :ref="value => setTaskElement(task.task_id, value)"
      class="task-capsule-anchor"
      :class="[
        `side-${taskPosition(task.task_id, index).side}`,
        {
          'is-dragging': draggingTaskId === task.task_id,
          'is-expanded': expandedTaskId === task.task_id,
        },
      ]"
      :style="taskStyle(task.task_id, index)"
      @click.capture="captureTaskClick"
    >
      <button
        class="task-capsule"
        :class="{
          'requires-action': taskRequiresAction(task),
          'is-expanded': expandedTaskId === task.task_id,
          'is-activating': hoppingTaskId === task.task_id,
        }"
        type="button"
        :aria-expanded="expandedTaskId === task.task_id"
        @pointerdown="startTaskDrag(task.task_id, index, $event)"
        @click="toggleExpandedTask(task.task_id)"
      >
        <span
          class="task-capsule-mascot"
          :class="{ 'is-hopping': hoppingTaskId === task.task_id }"
          aria-hidden="true"
        >
          <SubAgentMascot
            :status="task.status"
            :task-id="task.task_id"
            :awaiting-input="taskRequiresAction(task)"
            :size="36"
          />
        </span>
        <span class="task-capsule-copy">
          <span class="task-capsule-meta">
            <strong>{{ taskAgentName(task) }}</strong>
            <small v-if="taskModelName(task)" class="task-capsule-model">{{ taskModelName(task) }}</small>
            <small>{{ taskElapsedLabel(task) }}</small>
          </span>
          <span class="task-capsule-summary">{{ taskActivitySummary(task) }}</span>
        </span>
        <ContextUsageRing :value="taskContextWindow(task)" :size="30" />
        <span class="task-capsule-chevron" aria-hidden="true">⌄</span>
      </button>

      <Transition name="task-detail">
        <div
          v-if="expandedTaskId === task.task_id"
          class="task-capsule-detail-shell"
        >
          <div class="task-capsule-detail-clip">
            <BackgroundTaskPopover
              class="task-capsule-detail"
              :task="task"
              :title="taskAgentName(task)"
              :subtitle="taskModelName(task)"
              @close="expandedTaskId = null"
              @updated="reconcileOne"
              @deleted="removeTask"
            />
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance, CSSProperties } from 'vue'
import { backgroundTasksApi, type BackgroundTask } from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskPopover from './BackgroundTaskPopover.vue'
import SubAgentMascot from '@/components/brand/SubAgentMascot.vue'
import ContextUsageRing from './ContextUsageRing.vue'
import type { ContextWindowView } from '@/types/protocol'
import { backgroundTaskActivityText } from '@/utils/backgroundTaskActivity'

const props = withDefaults(defineProps<{
  sessionId?: string | null
  compact?: boolean
}>(), {
  sessionId: null,
  compact: false,
})

type DockSide = 'left' | 'right'
interface TaskPosition { side: DockSide; y: number }
interface TaskDragState {
  taskId: string
  pointerId: number
  offsetX: number
  offsetY: number
  x: number
  y: number
  originClientX: number
  originClientY: number
  moved: boolean
}

const { t } = useI18n()
const taskElements = new Map<string, HTMLElement>()
const layerRef = ref<HTMLElement | null>(null)
const tasks = ref<BackgroundTask[]>([])
const dismissedTaskIds = ref(new Set<string>())
const expandedTaskId = ref<string | null>(null)
const taskPositions = ref<Record<string, TaskPosition>>(loadTaskPositions())
const taskDrag = ref<TaskDragState | null>(null)
const suppressTaskClick = ref(false)
const hoppingTaskId = ref<string | null>(null)
let pollTimer: number | null = null
let elapsedTimer: number | null = null
let hopStartFrame: number | null = null
let hopEndTimer: number | null = null
let requestVersion = 0
let refreshInFlight = false
let refreshQueued = false
let hydratedSessionId = ''
const currentTime = ref(Date.now())
const TASK_SURFACE_WIDTH = 360

const draggingTaskId = computed(() => taskDrag.value?.taskId || null)

const visibleTasks = computed(() => {
  const active = tasks.value.filter(task => !isTerminal(task.status)).sort(compareNewest)
  const completed = tasks.value
    .filter(task => isTerminal(task.status))
    .sort(compareNewest)
  return [...active, ...completed].filter(task => !dismissedTaskIds.value.has(task.task_id))
})
const requiresAction = computed(() => visibleTasks.value.some(task => (
  task.pending_interaction?.kind === 'tool_approval'
  || task.pending_interaction?.kind === 'ask_user'
  || task.pending_interaction?.kind === 'resource_request'
)))

function loadTaskPositions(): Record<string, TaskPosition> {
  if (typeof window === 'undefined') return {}
  try {
    const stored = JSON.parse(window.localStorage.getItem('combo.backgroundTaskPositions') || '{}')
    if (!stored || typeof stored !== 'object') return {}
    return Object.fromEntries(
      Object.entries(stored).flatMap(([taskId, value]) => {
        const candidate = value as Partial<TaskPosition> | null
        if (
          (candidate?.side === 'left' || candidate?.side === 'right')
          && Number.isFinite(candidate.y)
        ) {
          return [[taskId, { side: candidate.side, y: clamp(Number(candidate.y), 0, 1) }]]
        }
        return []
      }),
    )
  } catch {
    return {}
  }
}

function saveTaskPositions() {
  window.localStorage.setItem('combo.backgroundTaskPositions', JSON.stringify(taskPositions.value))
}

function taskPosition(taskId: string, index: number): TaskPosition {
  return taskPositions.value[taskId] || {
    side: 'right',
    y: clamp(.58 + index * .1, 0, .9),
  }
}

function taskStyle(taskId: string, index: number): CSSProperties {
  const drag = taskDrag.value
  if (drag?.taskId === taskId) {
    return { left: `${drag.x}px`, right: 'auto', top: `${drag.y}px` }
  }
  const element = taskElements.get(taskId)
  const layer = layerRef.value
  const availableHeight = Math.max(0, (layer?.clientHeight || 0) - (element?.offsetHeight || 0) - 16)
  return { top: `${8 + availableHeight * taskPosition(taskId, index).y}px` }
}

function setTaskElement(taskId: string, value: Element | ComponentPublicInstance | null) {
  const element = value instanceof HTMLElement
    ? value
    : value && '$el' in value && value.$el instanceof HTMLElement
      ? value.$el
      : null
  if (element) taskElements.set(taskId, element)
  else taskElements.delete(taskId)
}

function startTaskDrag(taskId: string, index: number, event: PointerEvent) {
  if (event.button !== 0 || !layerRef.value) return
  const element = taskElements.get(taskId)
  if (!element) return
  const layerRect = layerRef.value.getBoundingClientRect()
  const itemRect = element.getBoundingClientRect()
  taskDrag.value = {
    taskId,
    pointerId: event.pointerId,
    offsetX: event.clientX - itemRect.left,
    offsetY: event.clientY - itemRect.top,
    x: itemRect.left - layerRect.left,
    y: itemRect.top - layerRect.top,
    originClientX: event.clientX,
    originClientY: event.clientY,
    moved: false,
  }
  window.addEventListener('pointermove', handleTaskDrag)
  window.addEventListener('pointerup', finishTaskDrag)
  window.addEventListener('pointercancel', finishTaskDrag)
  if (!taskPositions.value[taskId]) {
    taskPositions.value = { ...taskPositions.value, [taskId]: taskPosition(taskId, index) }
  }
}

function handleTaskDrag(event: PointerEvent) {
  const drag = taskDrag.value
  const layer = layerRef.value
  if (!drag || !layer || event.pointerId !== drag.pointerId) return
  const bounds = layer.getBoundingClientRect()
  const element = taskElements.get(drag.taskId)
  const width = element?.offsetWidth || TASK_SURFACE_WIDTH
  const height = element?.offsetHeight || 58
  drag.x = clamp(event.clientX - bounds.left - drag.offsetX, 8, Math.max(8, bounds.width - width - 8))
  drag.y = clamp(event.clientY - bounds.top - drag.offsetY, 8, Math.max(8, bounds.height - height - 8))
  if (Math.hypot(event.clientX - drag.originClientX, event.clientY - drag.originClientY) > 5) {
    drag.moved = true
  }
  taskDrag.value = { ...drag }
}

function finishTaskDrag(event: PointerEvent) {
  const drag = taskDrag.value
  const layer = layerRef.value
  if (!drag || !layer || event.pointerId !== drag.pointerId) return
  stopTaskDragListeners()
  if (!drag.moved) {
    taskDrag.value = null
    return
  }
  event.preventDefault()
  suppressTaskClick.value = true
  expandedTaskId.value = null
  const element = taskElements.get(drag.taskId)
  const side = drag.x + (element?.offsetWidth || TASK_SURFACE_WIDTH) / 2 < layer.clientWidth / 2 ? 'left' : 'right'
  const availableHeight = Math.max(1, layer.clientHeight - (element?.offsetHeight || 58) - 16)
  taskPositions.value = {
    ...taskPositions.value,
    [drag.taskId]: { side, y: clamp((drag.y - 8) / availableHeight, 0, 1) },
  }
  saveTaskPositions()
  taskDrag.value = null
  window.setTimeout(() => { suppressTaskClick.value = false }, 160)
}

function captureTaskClick(event: MouseEvent) {
  if (!suppressTaskClick.value) return
  event.preventDefault()
  event.stopPropagation()
}

function stopTaskDragListeners() {
  window.removeEventListener('pointermove', handleTaskDrag)
  window.removeEventListener('pointerup', finishTaskDrag)
  window.removeEventListener('pointercancel', finishTaskDrag)
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value))
}

function taskRequiresAction(task: BackgroundTask): boolean {
  const kind = task.pending_interaction?.kind
  return kind === 'tool_approval' || kind === 'ask_user' || kind === 'resource_request'
}

function taskAgentName(task: BackgroundTask): string {
  return String(task.agent_name || t('backgroundTask.memberFallback'))
}

function taskModelName(task: BackgroundTask): string {
  return String(task.model?.model_name || '').trim()
}

function taskContextWindow(task: BackgroundTask): ContextWindowView | null {
  const value = task.context_window
  if (!value || typeof value !== 'object') return null
  return {
    tokenCount: finiteNumber(value.token_count),
    contextWindowTokens: finiteNumber(value.context_window_tokens),
    compressionThresholdTokens: finiteNumber(value.compression_threshold_tokens),
    tokenCountMethod: String(value.token_count_method || '') || null,
    source: String(value.source || '') || null,
    modelRole: String(value.model_role || '') || null,
    nodeId: String(value.node_id || '') || null,
    compressionStatus: String(value.compression_status || '') || null,
    updatedAt: task.activity_updated_at || task.updated_at,
    payload: value,
  }
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function taskActivitySummary(task: BackgroundTask): string {
  if (task.pending_interaction?.kind === 'tool_approval') {
    return task.pending_interaction.message || t('backgroundTask.pendingApproval')
  }
  if (task.pending_interaction?.kind === 'ask_user' || task.pending_interaction?.kind === 'resource_request') {
    return task.pending_interaction.message || t('backgroundTask.pendingInput')
  }
  if (task.status === 'failed') return task.error?.message || t('backgroundTask.failedFallback')
  if (task.status === 'succeeded' && task.result_summary) return task.result_summary
  return backgroundTaskActivityText(task.activity_summary, t) || task.task_text || taskTypeLabel(task.status)
}

function taskElapsedLabel(task: BackgroundTask): string {
  const terminal = isTerminal(task.status)
  const duration = formatDuration(task.started_at || task.created_at, terminal ? task.completed_at || task.updated_at : null)
  return t(terminal ? 'backgroundTask.finishedIn' : 'backgroundTask.processedFor', { duration })
}

watch(requiresAction, (next, previous) => {
  if (!next || previous) return
  expandedTaskId.value = visibleTasks.value.find(taskRequiresAction)?.task_id || null
})

watch(
  () => props.sessionId,
  () => {
    requestVersion += 1
    stopPolling()
    tasks.value = []
    dismissedTaskIds.value = new Set()
    hydratedSessionId = ''
    expandedTaskId.value = null
    void refreshTasks(requestVersion)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  stopTaskDragListeners()
  requestVersion += 1
  stopPolling()
  stopElapsedClock()
  stopHopAnimation()
  window.removeEventListener('fastagentfactory:background-task-updated', handleTaskEvent)
  window.removeEventListener('combo:reopen-background-task', handleReopenTask)
})

onMounted(() => {
  window.addEventListener('fastagentfactory:background-task-updated', handleTaskEvent)
  window.addEventListener('combo:reopen-background-task', handleReopenTask)
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
    if (hydratedSessionId !== sessionId) {
      dismissedTaskIds.value = new Set(
        response.tasks.filter(task => isTerminal(task.status)).map(task => task.task_id),
      )
      hydratedSessionId = sessionId
    }
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
  dismissedTaskIds.value = new Set([...dismissedTaskIds.value, taskId])
  if (expandedTaskId.value === taskId) expandedTaskId.value = null
}

async function handleReopenTask(event: Event) {
  const taskId = String((event as CustomEvent<{ task_id?: string }>).detail?.task_id || '').trim()
  if (!taskId) return
  try {
    const response = await backgroundTasksApi.get(taskId)
    if (response.task.session_id !== String(props.sessionId || '').trim()) return
    reconcileOne(response.task)
    const nextDismissed = new Set(dismissedTaskIds.value)
    nextDismissed.delete(taskId)
    dismissedTaskIds.value = nextDismissed
    expandedTaskId.value = taskId
  } catch (error) {
    console.warn('Failed to reopen background task:', error)
  }
}

function toggleExpandedTask(taskId: string) {
  playHopAnimation(taskId)
  expandedTaskId.value = expandedTaskId.value === taskId ? null : taskId
}

function playHopAnimation(taskId: string) {
  stopHopAnimation()
  hoppingTaskId.value = null
  hopStartFrame = window.requestAnimationFrame(() => {
    hopStartFrame = window.requestAnimationFrame(() => {
      hopStartFrame = null
      hoppingTaskId.value = taskId
      hopEndTimer = window.setTimeout(() => {
        hoppingTaskId.value = null
        hopEndTimer = null
      }, 520)
    })
  })
}

function stopHopAnimation() {
  if (hopStartFrame !== null) window.cancelAnimationFrame(hopStartFrame)
  if (hopEndTimer !== null) window.clearTimeout(hopEndTimer)
  hopStartFrame = null
  hopEndTimer = null
  hoppingTaskId.value = null
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
.task-capsule-layer { position: absolute; z-index: 3; inset: 0; overflow: hidden; pointer-events: none; }
.task-capsule-anchor { position: absolute; pointer-events: auto; touch-action: none; user-select: none; }
.task-capsule-anchor.side-left { left: 12px; right: auto; }
.task-capsule-anchor.side-right { right: 12px; left: auto; }
.task-capsule-anchor.is-dragging,
.task-capsule-anchor.is-expanded { z-index: 4; }
.task-capsule-anchor.is-dragging { cursor: grabbing; }
.task-capsule { position: relative; z-index: 1; width: min(360px, calc(100vw - 48px)); min-height: 54px; display: flex; align-items: center; gap: 7px; padding: 6px 10px 6px 6px; outline: none; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); cursor: pointer; transition: border-color .18s ease, border-radius .26s cubic-bezier(.16, 1, .3, 1), transform .26s cubic-bezier(.16, 1, .3, 1); }
.task-capsule:hover { border-color: var(--app-border-hover); }
.task-capsule:focus-visible { border-color: var(--app-text); }
.task-capsule.requires-action { border-color: var(--app-text); }
.task-capsule.is-expanded { border-bottom-color: transparent; border-radius: var(--app-radius-lg) var(--app-radius-lg) 0 0; }
.task-capsule.is-activating { animation: capsule-activate .48s cubic-bezier(.2, .8, .2, 1) both; }
.task-capsule-detail-shell { position: absolute; top: calc(100% - 1px); width: 100%; display: grid; grid-template-rows: 1fr; transform-origin: top center; }
.task-capsule-detail-clip { min-height: 0; overflow: hidden; }
.task-capsule-detail { width: 100%; }
.task-detail-enter-active { transition: grid-template-rows .42s cubic-bezier(.16, 1, .3, 1), opacity .24s ease, transform .42s cubic-bezier(.16, 1, .3, 1); }
.task-detail-leave-active { transition: grid-template-rows .3s cubic-bezier(.7, 0, .84, 0), opacity .2s ease, transform .3s ease; }
.task-detail-enter-from, .task-detail-leave-to { grid-template-rows: 0fr; opacity: 0; transform: translateY(-8px) scaleX(.985); }
.task-capsule-mascot { width: 38px; height: 38px; flex: 0 0 auto; display: grid; place-items: center; }
.task-capsule-mascot.is-hopping { animation: mascot-hop .5s cubic-bezier(.2, .75, .25, 1) both; }
.task-capsule-copy { min-width: 0; flex: 1; display: grid; gap: 3px; text-align: left; }
.task-capsule-meta { min-width: 0; display: flex; align-items: baseline; gap: 6px; color: var(--app-text-muted); }
.task-capsule-meta strong, .task-capsule-meta small, .task-capsule-summary { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-capsule-meta strong { min-width: 0; color: var(--app-text); font-size: 12px; font-weight: 620; }
.task-capsule-meta small { font-size: 9px; }
.task-capsule-model { max-width: 88px; }
.task-capsule-summary { color: var(--app-text-secondary); font-size: 10px; line-height: 1.35; }
.task-capsule-chevron { flex: 0 0 auto; color: var(--app-text-muted); font-size: 11px; }
@keyframes mascot-hop {
  0% { transform: translateY(0) scale(1); }
  18% { transform: translateY(2px) scaleX(1.06) scaleY(.92); }
  48% { transform: translateY(-7px) scaleX(.96) scaleY(1.06); }
  72% { transform: translateY(1px) scaleX(1.04) scaleY(.95); }
  100% { transform: translateY(0) scale(1); }
}
@keyframes capsule-activate {
  0%, 100% { transform: translateY(0); }
  48% { transform: translateY(-2px); }
}
@media (prefers-reduced-motion: reduce) {
  .task-capsule, .task-detail-enter-active, .task-detail-leave-active { transition-duration: .01ms; }
  .task-capsule.is-activating, .task-capsule-mascot.is-hopping { animation: none; }
}
</style>
