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

    <section class="task-current">
      <span class="status-dot" :class="`dot-${normalizeStatus(view.status)}`" />
      <span>
        <strong>{{ currentTitle }}</strong>
        <small v-if="currentDescription && !view.delivery">{{ currentDescription }}</small>
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
          <ToolExecutionCard
            v-if="report.toolExecution"
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
import type { ChatMessagePartStatus, ToolExecutionMessagePart } from '@/types/protocol'
import { backgroundTaskActivityText } from '@/utils/backgroundTaskActivity'

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
let pollTimer: ReturnType<typeof setTimeout> | null = null

const projectedTask = computed(() => taskController().project?.(task.value, events.value) || task.value)
const interaction = computed(() => projectedTask.value.pending_interaction || null)
const view = computed(() => buildView(projectedTask.value, events.value, props.fallbackTitle || t('backgroundTask.title')))
const terminal = computed(() => ['succeeded', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const currentTitle = computed(() => localize(interaction.value?.title) || statusLabel.value)
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

onMounted(loadEvents)
onBeforeUnmount(stopPolling)
watch(() => props.task, value => { task.value = value }, { deep: true })
watch(() => props.task.task_id, () => {
  events.value = []
  void loadEvents()
})

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
    const phaseId = String(event.payload.phase_id || '').trim()
    const titleKey = String(event.payload.title_key || '').trim()
    const title = titleKey === 'backgroundTask.activity.current'
      ? ''
      : localize(titleKey) || String(event.payload.title || '').trim()
    const summary = localize(event.payload.summary_key)
      || backgroundTaskActivityText(event.payload.summary, t)
    if (!phaseId || !summary) continue
    const occurredAt = String(event.payload.occurred_at || event.created_at)
    const details = recordValue(event.payload.details)
    const previous = reportsByPhase.get(phaseId)
    reportsByPhase.set(phaseId, {
      phaseId,
      title,
      summary,
      status: String(event.payload.status || 'completed'),
      occurredAt,
      startedAt: previous?.startedAt || String(details?.started_at || details?.created_at || occurredAt),
      category: String(event.payload.category || 'activity'),
      details,
    })
  }
  const reports = Array.from(reportsByPhase.values())
    .sort((left, right) => Date.parse(right.occurredAt) - Date.parse(left.occurredAt))
    .map(report => ({ ...report, toolExecution: toolExecutionFromReport(report)[0] || null }))
  return {
    id: current.task_id,
    title: current.agent_name || fallbackTitle,
    objective: current.task_text,
    status: current.status,
    reports,
    latestSummary: reports.at(0)?.summary || '',
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

interface ActivityReport {
  phaseId: string
  title: string
  summary: string
  status: string
  occurredAt: string
  startedAt: string
  category: string
  details: Record<string, unknown> | null
  toolExecution?: ToolExecutionMessagePart | null
}

function toolExecutionFromReport(report: ActivityReport): ToolExecutionMessagePart[] {
  if (report.category !== 'tool' || !report.details) return []
  const details = report.details
  const toolName = String(details.model_alias || details.tool_name || details.tool_id || report.title || '').trim()
  if (!toolName) return []
  const errorCode = String(details.error_code || '').trim()
  return [{
    id: report.phaseId,
    type: 'tool_execution',
    toolName,
    callId: String(details.tool_call_id || '').trim() || null,
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

function formatTime(value: unknown): string {
  const parsed = new Date(String(value || ''))
  if (!Number.isFinite(parsed.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(parsed)
}

</script>

<style scoped>
.background-task-card { display: grid; gap: 13px; padding: 16px; color: var(--app-text); background: var(--app-surface); }
.task-header { display: flex; align-items: center; gap: 11px; }
.task-header:has(.task-status-label:first-child) { min-height: 28px; padding-right: 28px; }
.task-mark { width: 46px; height: 46px; display: grid; overflow: hidden; place-items: center; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface-muted); }
.task-heading { min-width: 0; flex: 1; display: grid; gap: 2px; padding-right: 22px; }
.task-status-label { flex: 0 0 auto; padding: 4px 8px; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text-secondary); font-size: 10px; }
.task-delete { flex: 0 0 auto; }
.task-heading strong { overflow-wrap: anywhere; font-size: 14px; }
.task-heading small { color: var(--app-text-muted); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; white-space: normal; }
.task-heading .task-model { width: fit-content; max-width: 100%; padding: 1px 6px; border-radius: 999px; background: var(--app-surface-muted); color: var(--app-text-secondary); font-size: 10px; }
.task-section small, .task-current small { color: var(--app-text-muted); font-size: 12px; line-height: 1.5; }
.task-current { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; padding: 12px; border: 1px solid var(--app-border); border-radius: 13px; }
.task-current > span:last-child { display: grid; gap: 3px; }
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
.interaction-options button { display: grid; gap: 3px; padding: 10px; text-align: left; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 11px; cursor: pointer; }
.interaction-options button.selected { border-color: var(--app-text); box-shadow: inset 0 0 0 1px var(--app-text); }
.interaction-options small { color: var(--app-text-muted); }
.interaction-actions { display: flex; justify-content: flex-end; }
.artifact-list { display: flex; flex-wrap: wrap; gap: 6px; }
.artifact-list span { padding: 5px 8px; border: 1px solid var(--app-border); border-radius: 8px; font-size: 11px; }
.task-delivery { min-width: 0; margin-top: 5px; color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; }
.task-notice { display: grid; gap: 4px; margin: 0; padding: 10px; border-radius: 10px; font-size: 12px; }
.task-notice-error { color: var(--app-error); background: color-mix(in srgb, var(--app-error) 8%, transparent); }
</style>
