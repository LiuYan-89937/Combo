<template>
  <div v-if="visibleRuns.length" ref="layerRef" class="scheduler-capsule-layer">
    <div
      v-for="(run, index) in visibleRuns"
      :key="run.run_id"
      :ref="value => setRunElement(run.run_id, value)"
      class="scheduler-capsule-anchor"
      :class="[`side-${runPosition(run.run_id, index).side}`, { 'is-dragging': draggingRunId === run.run_id, expanded: expandedRunId === run.run_id }]"
      :style="runStyle(run.run_id, index)"
      @pointerdown="startRunDrag(run.run_id, index, $event)"
      @click.capture="captureRunClick"
    >
      <n-popover
        :ref="value => setPopoverRef(run.run_id, value)"
        trigger="click"
        :show="expandedRunId === run.run_id"
        :placement="runPosition(run.run_id, index).side === 'left' ? 'bottom-start' : 'bottom-end'"
        :show-arrow="false"
        raw
        @update:show="setExpandedRun(run.run_id, $event)"
      >
        <template #trigger>
          <ActivityCapsule
            :title="capsuleTitle(run)"
            :subtitle="runSummary(run)"
            :active="isActive(run.status)"
            :expanded="expandedRunId === run.run_id"
          >
            <template #leading>
              <span class="scheduler-capsule-mark" aria-hidden="true"><n-icon size="16"><Time /></n-icon></span>
            </template>
            <template #actions>
              <small class="scheduler-capsule-elapsed">{{ elapsed(run) }}</small>
              <span class="capsule-grip" aria-hidden="true">⠿</span>
              <button
                type="button"
                @pointerdown.stop
                @click.stop="setExpandedRun(run.run_id, expandedRunId !== run.run_id)"
              >{{ expandedRunId === run.run_id ? '⌃' : '⌄' }}</button>
            </template>
          </ActivityCapsule>
        </template>

        <BackgroundTaskPopover
          :task="asBackgroundTask(run)"
          :title="capsuleTitle(run)"
          :fallback-title="capsuleTitle(run)"
          wide
          detached
          :controller="schedulerTaskController"
          @dismiss="dismissRun(run.run_id)"
          @updated="reconcileRun"
          @deleted="dismissRun"
        />
      </n-popover>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComponentPublicInstance, CSSProperties } from 'vue'
import { NIcon, NPopover } from 'naive-ui'
import { Time } from '@/components/icons'
import { schedulerApi } from '@/api/scheduler'
import type { SchedulerRunEventView, SchedulerRunView } from '@/api/resourceTypes'
import type {
  BackgroundTask,
  BackgroundTaskEvent,
  BackgroundTaskStatus,
  InteractionAction,
  PendingInteraction,
} from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskPopover from '@/components/chat/BackgroundTaskPopover.vue'
import type { BackgroundTaskController } from '@/components/chat/BackgroundTaskCard.vue'
import ActivityCapsule from '@/components/common/ActivityCapsule.vue'
import { schedulerActivity } from './schedulerActivity'

const props = defineProps<{ sessionId: string; workspaceId: string }>()
const { t } = useI18n()
const layerRef = ref<HTMLElement | null>(null)
const runs = ref<SchedulerRunView[]>([])
const expandedRunId = ref<string | null>(null)
const dismissed = ref(new Set<string>())
const runElements = new Map<string, HTMLElement>()
const popoverRefs = new Map<string, { syncPosition: () => void }>()
const positions = ref<Record<string, DockPosition>>(loadPositions())
const runDrag = ref<RunDragState | null>(null)
const suppressClick = ref(false)
const now = ref(Date.now())
let pollTimer: number | null = null
let elapsedTimer: number | null = null
let requestVersion = 0

type DockSide = 'left' | 'right'
interface DockPosition { side: DockSide; y: number }
interface RunDragState {
  runId: string
  pointerId: number
  offsetX: number
  offsetY: number
  x: number
  y: number
  originX: number
  originY: number
  moved: boolean
}

const POSITION_STORAGE_KEY = 'combo.schedulerRunCapsulePositions'
const TERMINAL_VISIBILITY_MS = 15 * 60 * 1000
const draggingRunId = computed(() => runDrag.value?.runId || null)
const visibleRuns = computed(() => runs.value.filter(run => {
  if (dismissed.value.has(run.run_id)) return false
  if (isActive(run.status)) return true
  const terminalAt = Date.parse(run.completed_at || '')
  return Number.isFinite(terminalAt) && now.value - terminalAt <= TERMINAL_VISIBILITY_MS
}).slice(0, 6))

const schedulerTaskController: BackgroundTaskController = {
  events: async (runId, after) => {
    const response = await schedulerApi.runEvents(runId, after)
    return {
      events: response.events.flatMap(event => {
        const activity = asBackgroundTaskEvent(event)
        return activity ? [activity] : []
      }),
    }
  },
  project: (task, events) => ({
    ...task,
    pending_interaction: interactionFromEvents(task, events),
  }),
  cancel: async current => {
    const response = await schedulerApi.cancelRun(current.task_id)
    return asBackgroundTask(response.run as unknown as SchedulerRunView)
  },
  delete: async current => {
    dismissRun(current.task_id)
    return true
  },
  resolveInteraction: async (current, interactionId, action, payload) => {
    const decision = schedulerDecision(action)
    const response = await schedulerApi.resolveInteraction(
      current.task_id,
      interactionId,
      decision,
      String(payload.answer || ''),
    )
    return asBackgroundTask(response.run as unknown as SchedulerRunView)
  },
}

watch(
  () => [props.sessionId, props.workspaceId],
  () => {
    requestVersion += 1
    stopPolling()
    runs.value = []
    expandedRunId.value = null
    void refresh(requestVersion)
  },
  { immediate: true },
)

onMounted(() => {
  elapsedTimer = window.setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  requestVersion += 1
  stopPolling()
  stopDragListeners()
  if (elapsedTimer !== null) window.clearInterval(elapsedTimer)
})

async function refresh(version: number): Promise<void> {
  const sessionId = String(props.sessionId || '').trim()
  const workspaceId = String(props.workspaceId || '').trim()
  if (!sessionId || !workspaceId) return
  try {
    const event = await schedulerApi.runs(undefined, 12, undefined, workspaceId, sessionId)
    if (version !== requestVersion) return
    const payload = event.payload?.payload || event.payload || {}
    runs.value = Array.isArray(payload.runs) ? payload.runs : []
  } finally {
    if (version === requestVersion) {
      pollTimer = window.setTimeout(() => void refresh(version), runs.value.some(run => isActive(run.status)) ? 1000 : 4000)
    }
  }
}

function stopPolling(): void {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
}

function reconcileRun(task: BackgroundTask): void {
  const index = runs.value.findIndex(run => run.run_id === task.task_id)
  if (index < 0) return
  runs.value.splice(index, 1, { ...runs.value[index], ...runPatchFromTask(task) })
}

function dismissRun(runId: string): void {
  dismissed.value = new Set([...dismissed.value, runId])
  if (expandedRunId.value === runId) expandedRunId.value = null
}

function asBackgroundTask(run: SchedulerRunView): BackgroundTask {
  const timestamp = run.started_at || run.scheduled_at
  const result = run.result || null
  return {
    task_id: run.run_id,
    session_id: props.sessionId,
    type: 'sub_agent',
    status: backgroundStatus(run.status),
    request_id: String(run.job_snapshot?.request_id || run.run_id),
    child_runtime_instance_id: String(run.result?.runtime_instance_id || run.job_snapshot?.runtime_instance_id || ''),
    agent_name: capsuleTitle(run),
    model: null,
    task_text: runTitle(run),
    activity_summary: runSummary(run),
    activity_updated_at: run.completed_at || timestamp,
    payload: { scheduler_run: true, executor_type: run.executor_type },
    delivery_standard: {},
    visible_context: {},
    depends_on: [],
    input_artifacts: [],
    artifact_refs: resultArtifacts(result),
    result_summary: delivery(run),
    result,
    error: schedulerError(run.error),
    pending_interaction: pendingInteraction(run),
    created_at: run.scheduled_at,
    updated_at: run.completed_at || run.started_at || run.scheduled_at,
    started_at: run.started_at,
    completed_at: run.completed_at,
    revision: 0,
  }
}

function asBackgroundTaskEvent(event: SchedulerRunEventView): BackgroundTaskEvent | null {
  const activity = schedulerActivity(event, key => t(key as any))
  if (!activity) return null
  return {
    seq: event.sequence,
    event_id: `${event.run_id}:${event.sequence}`,
    event_type: 'background_task_activity',
    created_at: event.created_at,
    task_id: event.run_id,
    payload: activity,
  }
}

function interactionFromEvents(task: BackgroundTask, events: BackgroundTaskEvent[]): PendingInteraction | null {
  if (!['waiting_approval', 'waiting_external'].includes(task.status)) return null
  const activity = [...events].reverse().find(event => {
    const details = recordValue(event.payload.details)
    return details?.scheduler_event_type === 'approval_required' || details?.scheduler_event_type === 'question'
  })
  const details = recordValue(activity?.payload.details)
  if (!details) return task.pending_interaction || null
  const interrupts = Array.isArray(details.interrupts) ? details.interrupts : []
  const interrupt = recordValue(interrupts[0]) || details
  const interactionId = String(interrupt.interrupt_id || interrupt.id || interrupt.question_id || '').trim()
  if (!interactionId) return task.pending_interaction || null
  const eventType = String(details.scheduler_event_type || '')
  return {
    interaction_id: interactionId,
    kind: eventType === 'approval_required' ? 'tool_approval' : 'ask_user',
    title: String(interrupt.title || (eventType === 'approval_required' ? 'tool.pendingApproval' : 'backgroundTask.activity.input')),
    message: String(interrupt.message || interrupt.prompt || ''),
    source: { scheduler_run_id: task.task_id },
    options: Array.isArray(interrupt.choices) ? interrupt.choices as PendingInteraction['options'] : [],
    requests: Array.isArray(interrupt.requests) ? interrupt.requests as Array<Record<string, unknown>> : [],
    resource_requests: [],
    payload: interrupt,
  }
}

function pendingInteraction(run: SchedulerRunView): PendingInteraction | null {
  if (!['waiting_approval', 'waiting_external'].includes(run.status)) return null
  const raw = recordValue(run.job_snapshot?.pending_interaction)
    || recordValue(run.result?.pending_interaction)
    || null
  const interactionId = String(raw?.interaction_id || raw?.interrupt_id || raw?.question_id || '').trim()
  if (!interactionId) return null
  return {
    interaction_id: interactionId,
    kind: run.status === 'waiting_approval' ? 'tool_approval' : 'ask_user',
    title: String(raw?.title || (run.status === 'waiting_approval' ? 'tool.pendingApproval' : 'backgroundTask.activity.input')),
    message: String(raw?.message || raw?.prompt || ''),
    source: { scheduler_run_id: run.run_id },
    options: Array.isArray(raw?.options) ? raw.options as PendingInteraction['options'] : [],
    requests: Array.isArray(raw?.requests) ? raw.requests as Array<Record<string, unknown>> : [],
    resource_requests: [],
    payload: raw || {},
  }
}

function backgroundStatus(status: SchedulerRunView['status']): BackgroundTaskStatus {
  if (status === 'completed') return 'succeeded'
  return status
}

function schedulerDecision(action: InteractionAction): 'approve' | 'reject' | 'trust' | 'answer' | 'revise' {
  if (action === 'deny') return 'reject'
  if (action === 'trust_tool') return 'trust'
  if (action === 'continue') return 'approve'
  return action
}

function runPatchFromTask(task: BackgroundTask): Partial<SchedulerRunView> {
  const status = task.status === 'succeeded' ? 'completed' : task.status
  return {
    status: status as SchedulerRunView['status'],
    result_summary: task.result_summary,
    result: task.result || undefined,
    error: task.error || undefined,
    completed_at: task.completed_at,
  }
}

function runTitle(run: SchedulerRunView): string {
  return String(run.job_snapshot?.task_content || run.task_content || t('scheduler.title'))
}

function capsuleTitle(run: SchedulerRunView): string {
  const name = String(run.job_snapshot?.display_name || '').trim()
  return `${t('scheduler.title')}${name ? ` · ${name}` : ''}`
}

function runSummary(run: SchedulerRunView): string {
  if (run.status === 'failed') return String(run.error?.message || t('scheduler.status.failed'))
  if (run.status === 'completed' && run.result_summary) return run.result_summary
  return runTitle(run)
}

function delivery(run: SchedulerRunView): string {
  return String(run.result?.content || run.result?.stdout || run.result_summary || '').trim()
}

function schedulerError(error: Record<string, unknown> | undefined): BackgroundTask['error'] {
  if (!error) return null
  return {
    code: String(error.code || ''),
    message: String(error.message || error.code || ''),
    details: error,
  }
}

function resultArtifacts(result: Record<string, unknown> | null): Array<Record<string, unknown>> {
  return result && Array.isArray(result.artifacts)
    ? result.artifacts.filter(item => item && typeof item === 'object') as Array<Record<string, unknown>>
    : []
}

function isActive(status: string): boolean {
  return ['queued', 'running', 'waiting_approval', 'waiting_external'].includes(status)
}

function elapsed(run: SchedulerRunView): string {
  const start = Date.parse(run.started_at || run.scheduled_at)
  const end = run.completed_at ? Date.parse(run.completed_at) : now.value
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function recordValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : null
}

function runPosition(runId: string, index: number): DockPosition {
  return positions.value[runId] || { side: 'right', y: clamp(.22 + index * .1, 0, .9) }
}

function runStyle(runId: string, index: number): CSSProperties {
  const drag = runDrag.value
  if (drag?.runId === runId) return { left: `${drag.x}px`, right: 'auto', top: `${drag.y}px` }
  const element = runElements.get(runId)
  const availableHeight = Math.max(0, (layerRef.value?.clientHeight || 0) - (element?.offsetHeight || 0) - 16)
  return { top: `${8 + availableHeight * runPosition(runId, index).y}px` }
}

function setRunElement(runId: string, value: Element | ComponentPublicInstance | null): void {
  const element = value instanceof HTMLElement
    ? value
    : value && '$el' in value && value.$el instanceof HTMLElement ? value.$el : null
  if (element) runElements.set(runId, element)
  else runElements.delete(runId)
}

function setPopoverRef(runId: string, value: Element | ComponentPublicInstance | null): void {
  if (value && 'syncPosition' in value) popoverRefs.set(runId, value as unknown as { syncPosition: () => void })
  else popoverRefs.delete(runId)
}

function setExpandedRun(runId: string, visible: boolean): void {
  expandedRunId.value = visible ? runId : null
}

function startRunDrag(runId: string, index: number, event: PointerEvent): void {
  if (event.button !== 0 || !layerRef.value) return
  const element = runElements.get(runId)
  if (!element) return
  const layerRect = layerRef.value.getBoundingClientRect()
  const itemRect = element.getBoundingClientRect()
  runDrag.value = {
    runId,
    pointerId: event.pointerId,
    offsetX: event.clientX - itemRect.left,
    offsetY: event.clientY - itemRect.top,
    x: itemRect.left - layerRect.left,
    y: itemRect.top - layerRect.top,
    originX: event.clientX,
    originY: event.clientY,
    moved: false,
  }
  if (!positions.value[runId]) positions.value = { ...positions.value, [runId]: runPosition(runId, index) }
  window.addEventListener('pointermove', moveRunDrag)
  window.addEventListener('pointerup', finishRunDrag)
  window.addEventListener('pointercancel', finishRunDrag)
}

function moveRunDrag(event: PointerEvent): void {
  const drag = runDrag.value
  const layer = layerRef.value
  if (!drag || !layer || event.pointerId !== drag.pointerId) return
  const bounds = layer.getBoundingClientRect()
  const element = runElements.get(drag.runId)
  drag.x = clamp(event.clientX - bounds.left - drag.offsetX, 8, Math.max(8, bounds.width - (element?.offsetWidth || 360) - 8))
  drag.y = clamp(event.clientY - bounds.top - drag.offsetY, 8, Math.max(8, bounds.height - (element?.offsetHeight || 48) - 8))
  if (Math.hypot(event.clientX - drag.originX, event.clientY - drag.originY) > 5) drag.moved = true
  runDrag.value = { ...drag }
  popoverRefs.get(drag.runId)?.syncPosition()
}

function finishRunDrag(event: PointerEvent): void {
  const drag = runDrag.value
  const layer = layerRef.value
  if (!drag || !layer || event.pointerId !== drag.pointerId) return
  stopDragListeners()
  if (drag.moved) {
    event.preventDefault()
    suppressClick.value = true
    expandedRunId.value = null
    const element = runElements.get(drag.runId)
    const side: DockSide = drag.x + (element?.offsetWidth || 360) / 2 < layer.clientWidth / 2 ? 'left' : 'right'
    const availableHeight = Math.max(1, layer.clientHeight - (element?.offsetHeight || 48) - 16)
    positions.value = { ...positions.value, [drag.runId]: { side, y: clamp((drag.y - 8) / availableHeight, 0, 1) } }
    window.localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(positions.value))
    window.setTimeout(() => { suppressClick.value = false }, 160)
  }
  runDrag.value = null
}

function captureRunClick(event: MouseEvent): void {
  if (!suppressClick.value) return
  event.preventDefault()
  event.stopPropagation()
}

function stopDragListeners(): void {
  window.removeEventListener('pointermove', moveRunDrag)
  window.removeEventListener('pointerup', finishRunDrag)
  window.removeEventListener('pointercancel', finishRunDrag)
}

function loadPositions(): Record<string, DockPosition> {
  if (typeof window === 'undefined') return {}
  try {
    const stored = JSON.parse(window.localStorage.getItem(POSITION_STORAGE_KEY) || '{}')
    if (!stored || typeof stored !== 'object') return {}
    return Object.fromEntries(Object.entries(stored).flatMap(([runId, raw]) => {
      const value = raw as Partial<DockPosition>
      return (value.side === 'left' || value.side === 'right') && Number.isFinite(value.y)
        ? [[runId, { side: value.side, y: clamp(Number(value.y), 0, 1) }]]
        : []
    }))
  } catch {
    return {}
  }
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value))
}
</script>

<style scoped>
.scheduler-capsule-layer { position: absolute; z-index: 4; inset: 0; overflow: hidden; pointer-events: none; }
.scheduler-capsule-anchor { position: absolute; width: min(340px, calc(100vw - 20px)); pointer-events: auto; touch-action: none; user-select: none; transition: width .26s cubic-bezier(.16, 1, .3, 1); }
.scheduler-capsule-anchor.expanded { width: min(460px, calc(100vw - 20px)); }
.scheduler-capsule-anchor :deep(.activity-capsule) { width: 100%; }
.scheduler-capsule-anchor.side-left { left: 12px; right: auto; }
.scheduler-capsule-anchor.side-right { right: 12px; left: auto; }
.scheduler-capsule-anchor.is-dragging { z-index: 5; cursor: grabbing; }
.scheduler-capsule-mark { width: 24px; height: 24px; flex: 0 0 auto; display: grid; place-items: center; color: var(--app-text-muted); }
.scheduler-capsule-elapsed { color: var(--app-text-muted); font-size: 9px; white-space: nowrap; }
.capsule-grip { padding: 5px 2px; color: var(--app-text-muted); cursor: grab; }
.scheduler-capsule-anchor button { border: 0; background: transparent; color: inherit; cursor: pointer; }
</style>
