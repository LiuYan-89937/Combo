<template>
  <article ref="rootRef" class="background-task-card" :class="`task-state-${view.status}`">
    <header class="task-header">
      <span v-if="!compactHeader" class="task-mark" aria-hidden="true">
        <SubAgentMascot
          :status="view.status"
          :task-id="view.id"
          :awaiting-input="Boolean(interaction)"
          :size="42"
        />
      </span>
      <span v-if="!compactHeader" class="task-heading">
        <strong>{{ view.title }}</strong>
        <small>{{ view.objective }}</small>
        <small v-if="task.model?.model_name" class="task-model">模型 · {{ task.model.model_name }}</small>
      </span>
      <span class="task-status-label">{{ statusLabel }}</span>
      <n-button
        v-if="!terminal"
        class="task-delete"
        size="tiny"
        quaternary
        :loading="cancelling"
        :disabled="view.status === 'cancelling'"
        @click="cancelTask"
      >
        {{ t('common.cancel') }}
      </n-button>
      <n-button
        v-if="terminal && props.controller"
        class="task-delete"
        size="tiny"
        quaternary
        :loading="deleting"
        @click="deleteTask"
      >
        {{ t('backgroundTask.delete') }}
      </n-button>
    </header>

    <!-- Scheduler runs render the live model output through the exact same
         conversation pipeline as the main chat (MessageItem → MessagePartRenderer /
         tool cards), so the run reads as a streamed assistant turn with no composer. -->
    <template v-if="schedulerRun">
      <section class="task-current">
        <span class="status-dot" :class="`dot-${normalizeStatus(view.status)}`" />
        <span>
          <strong>{{ currentTitle }}</strong>
          <small v-if="schedulerStatusDetail">{{ schedulerStatusDetail }}</small>
          <div
            v-if="!view.streamMessage && view.delivery"
            class="task-delivery markdown-content"
            v-html="renderedDelivery"
          ></div>
        </span>
      </section>

      <section v-if="view.streamMessage" class="task-stream">
        <MessageItem :message="view.streamMessage" :streaming="view.streaming" />
      </section>
    </template>

    <template v-else>
      <section class="task-current">
        <span class="status-dot" :class="`dot-${normalizeStatus(view.status)}`" />
        <span>
          <strong>{{ currentTitle }}</strong>
          <MessagePartRenderer
            v-if="view.livePart"
            :part="view.livePart"
            :streaming="view.liveStreaming"
          />
          <small v-else-if="currentDescription && !view.delivery">{{ currentDescription }}</small>
          <div
            v-if="view.delivery"
            class="task-delivery markdown-content"
            v-html="renderedDelivery"
          ></div>
        </span>
      </section>

      <details v-if="view.reports.length" class="task-section task-trace">
        <summary>{{ t('backgroundTask.activity') }}</summary>
        <div class="activity-chain">
          <div
            v-for="report in view.reports"
            :key="report.phaseId"
            class="activity-chain-item"
            :class="`activity-${report.category}`"
          >
            <span class="progress-report-rail" aria-hidden="true">
              <span class="status-dot" :class="`dot-${normalizeStatus(report.status)}`" />
            </span>
            <MessagePartRenderer
              v-if="report.messagePart"
              :part="report.messagePart"
              :streaming="report.streaming"
            />
            <ToolExecutionCard
              v-else-if="report.toolExecution"
              :part="report.toolExecution"
            />
            <span v-else class="activity-copy">
              <strong v-if="report.title">{{ report.title }}</strong>
              <small>{{ report.summary }}</small>
            </span>
            <time>{{ formatTime(report.occurredAt) }}</time>
          </div>
        </div>
      </details>
    </template>

    <section v-if="interaction" class="task-interaction">
      <div v-if="interaction.kind === 'tool_approval'" class="interaction-copy">
        <strong>{{ localize(interaction.title) }}</strong>
        <p>{{ t('backgroundTask.approvalInMainConversation') }}</p>
      </div>

      <template v-else-if="interaction.kind === 'ask_user'">
        <div class="interaction-copy">
          <strong>{{ interaction.title }}</strong>
          <p>{{ t('backgroundTask.questionInMainConversation') }}</p>
        </div>
      </template>

      <div v-else class="interaction-copy">
        <strong>{{ interaction.title }}</strong>
        <p>{{ interaction.message }}</p>
      </div>
    </section>

    <section v-if="view.artifacts.length" class="task-section">
      <h4>{{ t('backgroundTask.artifacts') }}</h4>
      <div class="artifact-list">
        <span v-for="artifact in view.artifacts" :key="artifact.key">{{ artifact.name }}</span>
      </div>
    </section>

    <p v-if="actionError" class="task-notice task-notice-error">{{ actionError }}</p>
    <section v-if="view.error" class="task-notice task-notice-error">
      <strong>{{ t('common.error') }}</strong>
      <span>{{ view.error }}</span>
    </section>
  </article>
</template>

<script lang="ts">
import type {
  BackgroundTask,
  BackgroundTaskEvent,
  InteractionAction,
} from '@/api/backgroundTasks'

export interface BackgroundTaskController {
  events: (taskId: string, after: number) => Promise<{ events: BackgroundTaskEvent[] }>
  project?: (task: BackgroundTask, events: BackgroundTaskEvent[]) => BackgroundTask
  cancel: (task: BackgroundTask) => Promise<BackgroundTask>
  delete: (task: BackgroundTask) => Promise<boolean>
  resolveInteraction: (
    task: BackgroundTask,
    interactionId: string,
    action: InteractionAction,
    payload: Record<string, unknown>,
  ) => Promise<BackgroundTask>
}
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import { backgroundTasksApi } from '@/api/backgroundTasks'
import SubAgentMascot from '@/components/brand/SubAgentMascot.vue'
import ToolExecutionCard from '@/components/chat/ToolExecutionCard.vue'
import MessagePartRenderer from '@/components/chat/MessagePartRenderer.vue'
import MessageItem from '@/components/chat/MessageItem.vue'
import type {
  ChatMessagePartStatus,
  ChatMessagePart,
  RuntimeFrontendEvent,
  ToolExecutionMessagePart,
  TranscriptItem,
} from '@/types/protocol'
import { backgroundTaskActivityText } from '@/utils/backgroundTaskActivity'
import { displayText } from '@/utils/displayText'
import { formatClockTime, parseDate } from '@/utils/format'

const props = defineProps<{
  task: BackgroundTask
  fallbackTitle?: string
  controller?: BackgroundTaskController
  compactHeader?: boolean
}>()
const emit = defineEmits<{ updated: [task: BackgroundTask]; deleted: [taskId: string] }>()
const { t } = useI18n()
const rootRef = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(rootRef)
const deleting = ref(false)
const cancelling = ref(false)
const actionError = ref('')
const task = ref<BackgroundTask>(props.task)
const events = ref<BackgroundTaskEvent[]>([])
const liveToolEvents = ref<Record<string, BackgroundTaskEvent>>({})
let pollTimer: ReturnType<typeof setTimeout> | null = null

const projectedTask = computed(() => taskController().project?.(task.value, events.value) || task.value)
const interaction = computed(() => projectedTask.value.pending_interaction || null)
const view = computed(() => buildView(
  projectedTask.value,
  [...events.value, ...Object.values(liveToolEvents.value)],
  props.fallbackTitle || t('backgroundTask.title'),
))
const terminal = computed(() => ['succeeded', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const currentTitle = computed(() => localize(interaction.value?.title) || statusLabel.value)
/**
 * Scheduler runs are tagged by `asBackgroundTask` in SchedulerRunCapsules. They
 * reuse the conversation renderer instead of the phase-report activity chain.
 */
const schedulerRun = computed(() => task.value.payload?.scheduler_run === true)
const schedulerStatusDetail = computed(() => (
  interaction.value?.message
  || (projectedTask.value.status === 'failed' ? projectedTask.value.error?.message : '')
  || ''
))
const currentDescription = computed(() => (
  interaction.value?.message
  || (projectedTask.value.status === 'failed' ? projectedTask.value.error?.message : '')
  || backgroundTaskActivityText(projectedTask.value.activity_summary, t)
  || view.value.latestSummary
  || t(`backgroundTask.description.${projectedTask.value.status}` as any)
))
const renderedDelivery = computed(() => renderMarkdown(view.value.delivery, {
  surface: 'chat_message',
}))

onMounted(() => {
  window.addEventListener('combo:background-task-runtime-event', handleRuntimeToolEvent)
  void loadEvents()
})
onBeforeUnmount(() => {
  window.removeEventListener('combo:background-task-runtime-event', handleRuntimeToolEvent)
  stopPolling()
})
watch(() => props.task, value => { task.value = value }, { deep: true })
watch(() => props.task.task_id, () => {
  events.value = []
  liveToolEvents.value = {}
  void loadEvents()
})

function handleRuntimeToolEvent(event: Event) {
  const runtimeEvent = (event as CustomEvent<RuntimeFrontendEvent>).detail
  const payload = recordValue(runtimeEvent?.payload)
  if (!payload || String(payload.source_task_id || '') !== task.value.task_id) return
  const toolCallId = String(payload.tool_call_id || '').trim()
  if (!toolCallId) return
  const previous = liveToolEvents.value[toolCallId]
  const occurredAt = String(runtimeEvent.timestamp || previous?.created_at || '').trim()
  const status = runtimeToolStatus(runtimeEvent.event_type, payload.status)
  const toolName = String(
    payload.tool_name
    || payload.tool_id
    || recordValue(previous?.payload.details)?.tool_name
    || '',
  ).trim()
  if (!toolName) return
  const previousDetails = recordValue(previous?.payload.details) || {}
  const details = {
    ...previousDetails,
    ...payload,
    started_at: previousDetails.started_at
      || (runtimeEvent.event_type === 'tool_call_started' ? occurredAt : null),
    updated_at: occurredAt,
  }
  liveToolEvents.value = {
    ...liveToolEvents.value,
    [toolCallId]: {
      seq: previous?.seq || 0,
      event_id: String(runtimeEvent.event_id || `${task.value.task_id}:${toolCallId}:${runtimeEvent.event_type}`),
      event_type: 'background_task_activity',
      created_at: occurredAt,
      request_id: runtimeEvent.request_id,
      task_id: task.value.task_id,
      session_id: task.value.session_id,
      payload: {
        phase_id: `tool:${toolCallId}`,
        category: 'tool',
        title: toolName,
        summary: `${toolName} ${status}`,
        status,
        details,
      },
    },
  }
}

function runtimeToolStatus(eventType: string, value: unknown): string {
  if (eventType === 'tool_call_failed' || eventType === 'tool_contract_invalid') return 'failed'
  if (eventType === 'tool_call_completed' || eventType === 'tool_observation_available') return 'completed'
  const status = String(value || '').trim()
  if (status) return status
  return 'running'
}

async function loadEvents() {
  if (!task.value.task_id) return
  try {
    const eventResponse = await taskController().events(task.value.task_id, events.value.at(-1)?.seq || 0)
    const known = new Set(events.value.map(item => item.seq))
    for (const event of eventResponse.events) {
      if (!known.has(event.seq)) events.value.push(event)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
  if (!terminal.value) schedulePoll()
}

async function deleteTask() {
  if (!terminal.value || deleting.value) return
  deleting.value = true
  actionError.value = ''
  try {
    const deleted = props.controller
      ? await taskController().delete(task.value)
      : true
    if (deleted) emit('deleted', task.value.task_id)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    deleting.value = false
  }
}

async function cancelTask() {
  if (terminal.value || cancelling.value || task.value.status === 'cancelling') return
  cancelling.value = true
  actionError.value = ''
  try {
    task.value = await taskController().cancel(task.value)
    emit('updated', task.value)
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    cancelling.value = false
  }
}

function schedulePoll() {
  stopPolling()
  pollTimer = setTimeout(() => void loadEvents(), 2000)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function taskController(): BackgroundTaskController {
  return props.controller || defaultController
}

const defaultController: BackgroundTaskController = {
  events: (taskId, after) => backgroundTasksApi.events(taskId, after),
  cancel: async current => (await backgroundTasksApi.cancel(current.task_id, 'user_cancelled')).task,
  delete: async current => (await backgroundTasksApi.delete(current.task_id)).deleted,
  resolveInteraction: async (current, interactionId, action, payload) => (
    await backgroundTasksApi.resolveInteraction(current.task_id, interactionId, action, payload)
  ).task,
}

function buildView(current: BackgroundTask, timeline: BackgroundTaskEvent[], fallbackTitle: string) {
  const reportsByPhase = new Map<string, ActivityReport>()
  for (const event of timeline) {
    if (event.event_type !== 'background_task_activity') continue
    const phaseId = displayText(event.payload.phase_id)
    const titleKey = displayText(event.payload.title_key)
    const title = titleKey === 'backgroundTask.activity.current'
      ? ''
      : localize(titleKey) || displayText(event.payload.title)
    const incomingDetails = recordValue(event.payload.details)
    const previous = reportsByPhase.get(phaseId)
    const details = mergeActivityDetails(previous?.details, incomingDetails)
    const streamKind = streamKindOf(event.payload, details)
    const streamFormat = streamFormatOf(event.payload, details)
    const streamText = streamKind
      ? mergeStreamText(previous?.streamText || '', details, previous?.details)
      : ''
    const summary = streamKind
      ? streamText || localize(event.payload.summary_key) || backgroundTaskActivityText(event.payload.summary, t)
      : localize(event.payload.summary_key)
        || backgroundTaskActivityText(event.payload.summary, t)
        || activitySummary(details, event.payload)
    if (!phaseId || !summary) continue
    const occurredAt = String(event.payload.occurred_at || event.created_at)
    reportsByPhase.set(phaseId, {
      phaseId,
      title,
      summary,
      status: String(event.payload.status || previous?.status || 'completed'),
      occurredAt,
      startedAt: previous?.startedAt || String(details?.started_at || details?.created_at || occurredAt),
      category: String(event.payload.category || 'activity'),
      details,
      streamKind,
      streamText,
      streaming: streamKind
        ? String(event.payload.status || '') === 'running'
          && !['succeeded', 'failed', 'cancelled'].includes(current.status)
        : false,
      streamFormat,
    })
  }
  const orderedReports = Array.from(reportsByPhase.values())
    .sort((left, right) => parseReportTime(left.startedAt || left.occurredAt)
      - parseReportTime(right.startedAt || right.occurredAt))
    .map(report => ({
      ...report,
      messagePart: messagePartFromReport(report),
      toolExecution: toolExecutionFromReport(report)[0] || null,
    }))
  const reports = [...orderedReports].sort(
    (left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt),
  )
  const liveReport = reports.find(report => report.streaming && report.messagePart)
  return {
    id: current.task_id,
    title: current.agent_name || fallbackTitle,
    objective: current.task_text,
    status: current.status,
    reports,
    streamMessage: streamTranscriptMessage(current, orderedReports),
    streaming: Boolean(liveReport?.streaming),
    latestSummary: reports.at(0)?.summary || '',
    livePart: liveReport?.messagePart || null,
    liveStreaming: Boolean(liveReport?.streaming),
    artifacts: artifactViews(current),
    delivery: current.result_summary || '',
    error: String(
      current.error?.message
      || current.error?.details?.message
      || current.error?.code
      || '',
    ),
  }
}

/**
 * Fold a run's phase reports into a single assistant turn so the scheduler panel
 * can render the run through the shared conversation components. Only model /
 * process stream and tool reports become parts; pure status rows (agent queued,
 * run started, …) carry no message content and are dropped.
 */
function streamTranscriptMessage(
  current: BackgroundTask,
  orderedReports: ActivityReport[],
): TranscriptItem | null {
  const parts: ChatMessagePart[] = []
  for (const report of orderedReports) {
    if (report.messagePart) parts.push(report.messagePart)
    else if (report.toolExecution) parts.push(report.toolExecution)
  }
  if (parts.length === 0) return null
  return {
    id: `scheduler-run-${current.task_id}`,
    role: 'assistant',
    parts,
    content: '',
    timestamp: String(
      orderedReports[0]?.startedAt
      || orderedReports[0]?.occurredAt
      || current.started_at
      || current.created_at,
    ),
    metadata: {},
  }
}

interface ActivityReport {
  phaseId: string
  title: string
  summary: string
  status: string
  occurredAt: string
  startedAt: string
  category: string
  details: Record<string, unknown> | null
  streamKind?: 'output' | 'reasoning' | null
  streamFormat?: 'markdown' | 'plain'
  streamText?: string
  streaming?: boolean
  messagePart?: ChatMessagePart | null
  toolExecution?: ToolExecutionMessagePart | null
}

function mergeActivityDetails(
  previous: Record<string, unknown> | null | undefined,
  current: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (!previous && !current) return null
  const merged = { ...(previous || {}) }
  for (const [key, value] of Object.entries(current || {})) {
    if (value !== null && value !== undefined && value !== '') merged[key] = value
  }
  const eventType = String(current?.event_type || '')
  if (eventType === 'tool_call_output_delta') {
    const delta = String(current?.delta ?? current?.output ?? '')
    const output = String(previous?.output || '')
    if (delta) merged.output = output + delta
  }
  return merged
}

function streamKindOf(
  payload: Record<string, unknown>,
  details: Record<string, unknown> | null,
): 'output' | 'reasoning' | null {
  const value = String(payload.stream_kind || details?.stream_kind || '').trim()
  return value === 'output' || value === 'reasoning' ? value : null
}

function streamFormatOf(
  payload: Record<string, unknown>,
  details: Record<string, unknown> | null,
): 'markdown' | 'plain' {
  return String(payload.stream_format || details?.stream_format || '').trim() === 'plain'
    ? 'plain'
    : 'markdown'
}

function mergeStreamText(
  previous: string,
  details: Record<string, unknown> | null,
  previousDetails: Record<string, unknown> | null | undefined,
): string {
  const delta = String(details?.delta || '')
  const snapshot = String(details?.content || '')
  let text = previous
  if (delta) text += delta
  if (snapshot && (!text || snapshot.length >= text.length)) text = snapshot
  if (!text && previousDetails) {
    text = String(previousDetails.content || previousDetails.delta || '')
  }
  return text
}

function activitySummary(
  details: Record<string, unknown> | null,
  payload: Record<string, unknown>,
): string {
  const toolName = displayText(details?.tool_name || details?.tool_id || payload.title)
  const status = displayText(payload.status || details?.status)
  if (toolName && status) return `${toolName} ${status}`
  return displayText(details?.message) || displayText(payload.title)
}

function messagePartFromReport(report: ActivityReport): ChatMessagePart | null {
  if (!report.streamKind || !report.streamText) return null
  const common = {
    id: report.phaseId,
    status: report.streaming ? 'streaming' as const : 'completed' as const,
    createdAt: report.occurredAt,
    startedAt: report.startedAt,
    updatedAt: report.occurredAt,
  }
  if (report.streamKind === 'reasoning') {
    return { ...common, type: 'reasoning', text: report.streamText }
  }
  return { ...common, type: 'text', format: report.streamFormat || 'markdown', text: report.streamText }
}

function toolExecutionFromReport(report: ActivityReport): ToolExecutionMessagePart[] {
  if (report.category !== 'tool' || !report.details) return []
  const details = report.details
  const toolName = displayText(details.model_alias || details.tool_name || details.tool_id || report.title)
  if (!toolName) return []
  const errorCode = displayText(details.error_code)
  return [{
    id: report.phaseId,
    type: 'tool_execution',
    toolName,
    callId: displayText(details.tool_call_id) || null,
    arguments: details.arguments ?? {},
    output: details.result ?? details.output ?? details.observation ?? null,
    error: errorCode || (typeof details.error === 'string' ? details.error : undefined),
    approvalState: report.status === 'approval' ? 'pending' : undefined,
    artifacts: [],
    status: toolMessageStatus(report.status),
    createdAt: String(details.created_at || report.occurredAt),
    startedAt: report.startedAt,
    updatedAt: String(details.updated_at || report.occurredAt),
  }]
}

function toolMessageStatus(status: string): ChatMessagePartStatus {
  if (status === 'waiting_approval') return 'awaiting_approval'
  if (status === 'proposed') return 'requested'
  if (status === 'running') return 'running'
  if (status === 'failed' || status === 'rejected' || status === 'timed_out') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  return 'completed'
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function artifactViews(current: BackgroundTask): Array<{ key: string; name: string }> {
  const artifacts = new Map<string, { key: string; name: string }>()
  for (const artifact of current.artifact_refs || []) {
    const key = String(artifact?.path || artifact?.id || '')
    if (key) artifacts.set(key, { key, name: String(artifact?.name || artifact?.path || key) })
  }
  return Array.from(artifacts.values())
}

function normalizeStatus(status: unknown): string {
  const value = String(status || '')
  return value === 'succeeded' ? 'succeeded' : value === 'failed' ? 'failed' : value === 'cancelled' ? 'cancelled' : 'running'
}

function localize(value: unknown): string {
  const key = String(value || '').trim()
  return key ? t(key as any) : ''
}

function parseReportTime(value: unknown): number {
  const parsed = Date.parse(String(value || ''))
  return Number.isFinite(parsed) ? parsed : 0
}

function formatTime(value: unknown): string {
  const parsed = parseDate(value || '')
  return parsed ? formatClockTime(parsed) : ''
}

</script>

<style scoped>
.background-task-card { display: grid; gap: 13px; padding: 16px; color: var(--app-text); background: var(--app-surface); }
.task-header { display: flex; align-items: center; gap: 11px; }
.task-header:has(.task-status-label:first-child) { min-height: 28px; padding-right: 28px; }
.task-mark { width: 46px; height: 46px; display: grid; overflow: hidden; place-items: center; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface-muted); }
.task-heading { min-width: 0; flex: 1; display: grid; gap: 2px; padding-right: 22px; }
.task-status-label { flex: 0 0 auto; padding: 4px 8px; border: 1px solid var(--app-border); border-radius: var(--app-radius-pill); color: var(--app-text-secondary); font-size: 10px; }
.task-delete { flex: 0 0 auto; }
.task-heading strong { overflow-wrap: anywhere; font-size: 14px; }
.task-heading small { color: var(--app-text-muted); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; white-space: normal; }
.task-heading .task-model { width: fit-content; max-width: 100%; padding: 1px 6px; border-radius: var(--app-radius-pill); background: var(--app-surface-muted); color: var(--app-text-secondary); font-size: 10px; }
.task-section small, .task-current small { color: var(--app-text-muted); font-size: 12px; line-height: 1.5; }
.task-current { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; padding: 12px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); }
.task-current > span:last-child { display: grid; gap: 3px; }
/* Scheduler runs render the live model output as a conversation turn, so the
   transcript inherits the main chat look and only drops the message padding. */
.task-stream { min-width: 0; }
.task-stream :deep(.message-item) { padding-inline: 0; }
.status-dot { width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: var(--app-text-muted); }
.dot-running { background: var(--app-text); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-text) 10%, transparent); }
.dot-succeeded { background: var(--app-success); }
.dot-failed, .dot-cancelled { background: var(--app-error); }
.task-section { display: grid; gap: 9px; }
.task-trace > summary { display: flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; cursor: pointer; list-style: none; }
.task-trace > summary::-webkit-details-marker { display: none; }
.task-trace > summary::before { content: '⌄'; color: var(--app-text-muted); transition: transform .18s ease; }
.task-trace:not([open]) > summary::before { transform: rotate(-90deg); }
.task-trace[open] > summary { margin-bottom: 9px; }
.activity-chain { display: grid; }
.activity-chain-item { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 0; align-items: stretch; min-width: 0; }
.activity-chain-item :deep(.tool-execution-card) { min-width: 0; margin: 0 0 8px; border: 0; border-radius: var(--app-radius-sm); background: transparent; box-shadow: none; }
.activity-chain-item :deep(.tool-summary) { min-height: 40px; padding: 5px 7px; }
.activity-chain-item :deep(.tool-body) { margin: 0 7px 8px; border: 1px solid var(--app-divider); border-radius: var(--app-radius-sm); }
.progress-report-rail { position: relative; display: flex; justify-content: center; }
.progress-report-rail::after { content: ''; position: absolute; top: 18px; bottom: -14px; width: 1px; background: var(--app-border-hover); }
.activity-chain-item:last-child .progress-report-rail::after { display: none; }
.progress-report-rail .status-dot { position: relative; z-index: 1; margin-top: 5px; border: 2px solid var(--app-surface); box-shadow: 0 0 0 1px var(--app-border-hover); }
.activity-copy { display: grid; gap: 2px; padding-bottom: 10px; }
.activity-chain-item time { padding-top: 2px; color: var(--app-text-muted); font-size: 10px; }
.task-interaction { display: grid; gap: 12px; }
.task-interaction :deep(.tool-approval-panel), .task-interaction :deep(.resource-request-panel) { padding: 14px; box-shadow: none; }
.interaction-copy { display: grid; gap: 5px; }
.interaction-copy p { margin: 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.interaction-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.interaction-options button { display: grid; gap: 3px; padding: 10px; text-align: left; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); cursor: pointer; }
.interaction-options button.selected { border-color: var(--app-text); box-shadow: inset 0 0 0 1px var(--app-text); }
.interaction-options small { color: var(--app-text-muted); }
.interaction-actions { display: flex; justify-content: flex-end; }
.artifact-list { display: flex; flex-wrap: wrap; gap: 6px; }
.artifact-list span { padding: 5px 8px; border: 1px solid var(--app-border); border-radius: var(--app-radius-sm); font-size: 11px; }
.task-delivery { min-width: 0; margin-top: 5px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }
.task-notice { display: grid; gap: 4px; margin: 0; padding: 10px; border-radius: var(--app-radius-sm); font-size: 12px; }
.task-notice-error { color: var(--app-error); background: color-mix(in srgb, var(--app-error) 8%, transparent); }
</style>
