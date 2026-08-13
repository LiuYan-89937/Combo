<template>
  <article ref="rootRef" class="background-task-card" :class="`task-state-${view.status}`">
    <header class="task-header">
      <span class="task-mark" aria-hidden="true">
        <SubAgentMascot
          :status="view.status"
          :task-id="view.id"
          :awaiting-input="Boolean(interaction)"
          :size="42"
        />
      </span>
      <span class="task-heading">
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
        v-if="terminal"
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

    <section v-if="view.reports.length" class="task-section">
      <h4>{{ t('backgroundTask.activity') }}</h4>
      <ToolExecutionChain v-if="view.toolExecutions.length" :executions="view.toolExecutions" />
      <div v-if="view.progressReports.length" class="progress-report-list">
        <div v-for="report in view.progressReports" :key="report.phaseId" class="progress-report-item">
          <span class="status-dot" :class="`dot-${normalizeStatus(report.status)}`" />
          <span>
            <strong>{{ report.title }}</strong>
            <small>{{ report.summary }}</small>
          </span>
          <time>{{ formatTime(report.occurredAt) }}</time>
        </div>
      </div>
    </section>

    <section v-if="interaction" class="task-interaction">
      <div v-if="interaction.kind === 'tool_approval'" class="interaction-copy">
        <strong>{{ localize(interaction.title) }}</strong>
        <p>{{ t('backgroundTask.approvalInMainConversation') }}</p>
      </div>

      <template v-else-if="interaction.kind === 'ask_user'">
        <div class="interaction-copy">
          <strong>{{ interaction.title }}</strong>
          <p>{{ interaction.message }}</p>
        </div>
        <div v-if="interaction.options.length" class="interaction-options">
          <button
            v-for="option in interaction.options"
            :key="String(option.value || option.label)"
            type="button"
            :class="{ selected: selectedOption === option.value }"
            @click="selectOption(String(option.value || option.label || ''))"
          >
            <strong>{{ option.label || option.value }}</strong>
            <small v-if="option.description">{{ option.description }}</small>
          </button>
        </div>
        <n-input
          v-if="allowFreeText"
          v-model:value="answerText"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          :placeholder="t('backgroundTask.responsePlaceholder')"
          @update:value="selectedOption = ''"
        />
        <div class="interaction-actions">
          <n-button
            size="small"
            type="primary"
            :loading="submitting"
            :disabled="!canSubmitAnswer"
            @click="submitAnswer"
          >
            {{ t('backgroundTask.submitResponse') }}
          </n-button>
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

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NInput } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import {
  backgroundTasksApi,
  type BackgroundTask,
  type BackgroundTaskEvent,
  type InteractionAction,
} from '@/api/backgroundTasks'
import SubAgentMascot from '@/components/brand/SubAgentMascot.vue'
import ToolExecutionChain from '@/components/chat/ToolExecutionChain.vue'
import type { ChatMessagePartStatus, ToolExecutionMessagePart } from '@/types/protocol'

const props = defineProps<{ task: BackgroundTask; fallbackTitle?: string }>()
const emit = defineEmits<{ updated: [task: BackgroundTask]; deleted: [taskId: string] }>()
const { t } = useI18n()
const rootRef = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(rootRef)
const submitting = ref(false)
const deleting = ref(false)
const cancelling = ref(false)
const answerText = ref('')
const selectedOption = ref('')
const actionError = ref('')
const task = ref<BackgroundTask>(props.task)
const events = ref<BackgroundTaskEvent[]>([])
let pollTimer: ReturnType<typeof setTimeout> | null = null

const interaction = computed(() => task.value.pending_interaction || null)
const view = computed(() => buildView(task.value, events.value, props.fallbackTitle || t('backgroundTask.title')))
const terminal = computed(() => ['succeeded', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const currentTitle = computed(() => localize(interaction.value?.title) || statusLabel.value)
const currentDescription = computed(() => (
  interaction.value?.message
  || (task.value.status === 'failed' ? task.value.error?.message : '')
  || task.value.activity_summary
  || view.value.latestSummary
  || t(`backgroundTask.description.${task.value.status}` as any)
))
const renderedDelivery = computed(() => renderMarkdown(view.value.delivery, {
  surface: 'chat_message',
}))
const allowFreeText = computed(() => interaction.value?.payload.allow_free_text !== false)
const canSubmitAnswer = computed(() => Boolean(answerText.value.trim() || selectedOption.value))

onMounted(loadEvents)
onBeforeUnmount(stopPolling)
watch(() => props.task, value => { task.value = value }, { deep: true })
watch(() => props.task.task_id, () => {
  events.value = []
  answerText.value = ''
  selectedOption.value = ''
  void loadEvents()
})

async function loadEvents() {
  if (!task.value.task_id) return
  try {
    const eventResponse = await backgroundTasksApi.events(task.value.task_id, events.value.at(-1)?.seq || 0)
    const known = new Set(events.value.map(item => item.seq))
    for (const event of eventResponse.events) {
      if (!known.has(event.seq)) events.value.push(event)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
  if (!terminal.value) schedulePoll()
}

async function submitAnswer() {
  const answer = answerText.value.trim() || selectedOption.value
  if (!answer) return
  await resolveInteraction('answer', {
    answer,
    selected_values: selectedOption.value ? [selectedOption.value] : [],
  })
}

function selectOption(value: string) {
  selectedOption.value = value
  answerText.value = ''
}

async function resolveInteraction(action: InteractionAction, payload: Record<string, unknown>) {
  const pending = interaction.value
  if (!pending || submitting.value) return
  submitting.value = true
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.resolveInteraction(
      task.value.task_id,
      pending.interaction_id,
      action,
      payload,
    )).task
    answerText.value = ''
    selectedOption.value = ''
    emit('updated', task.value)
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function deleteTask() {
  if (!terminal.value || deleting.value) return
  deleting.value = true
  actionError.value = ''
  try {
    const response = await backgroundTasksApi.delete(task.value.task_id)
    if (response.deleted) emit('deleted', task.value.task_id)
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
    task.value = (await backgroundTasksApi.cancel(task.value.task_id, 'user_cancelled')).task
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

function buildView(current: BackgroundTask, timeline: BackgroundTaskEvent[], fallbackTitle: string) {
  const reportsByPhase = new Map<string, ActivityReport>()
  for (const event of timeline) {
    if (event.event_type !== 'background_task_activity') continue
    const phaseId = String(event.payload.phase_id || '').trim()
    const title = localize(event.payload.title_key) || String(event.payload.title || '').trim()
    const summary = localize(event.payload.summary_key) || String(event.payload.summary || '').trim()
    if (!phaseId || !title || !summary) continue
    reportsByPhase.set(phaseId, {
      phaseId,
      title,
      summary,
      status: String(event.payload.status || 'completed'),
      occurredAt: String(event.payload.occurred_at || event.created_at),
      category: String(event.payload.category || 'activity'),
      details: recordValue(event.payload.details),
    })
  }
  const reports = Array.from(reportsByPhase.values()).sort((left, right) => (
    Date.parse(right.occurredAt) - Date.parse(left.occurredAt)
  ))
  return {
    id: current.task_id,
    title: current.agent_name || fallbackTitle,
    objective: current.task_text,
    status: current.status,
    reports,
    toolExecutions: reports.flatMap(toolExecutionFromReport),
    progressReports: reports.filter(report => report.category !== 'tool'),
    latestSummary: reports[0]?.summary || '',
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
  category: string
  details: Record<string, unknown> | null
}

function toolExecutionFromReport(report: ActivityReport): ToolExecutionMessagePart[] {
  if (report.category !== 'tool' || !report.details) return []
  const details = report.details
  const toolName = String(details.model_alias || report.title || '').trim()
  if (!toolName) return []
  const errorCode = String(details.error_code || '').trim()
  return [{
    id: report.phaseId,
    type: 'tool_execution',
    toolName,
    callId: String(details.tool_call_id || '').trim() || null,
    arguments: details.arguments ?? {},
    output: details.result ?? null,
    error: errorCode || undefined,
    approvalState: report.status === 'approval' ? 'pending' : undefined,
    artifacts: [],
    status: toolMessageStatus(report.status),
    createdAt: String(details.created_at || report.occurredAt),
    startedAt: String(details.created_at || report.occurredAt),
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
.background-task-card { display: grid; gap: 16px; padding: 18px; color: var(--app-text); background: var(--app-surface); }
.task-header { display: flex; align-items: center; gap: 11px; }
.task-mark { width: 46px; height: 46px; display: grid; overflow: hidden; place-items: center; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface-muted); }
.task-heading { min-width: 0; flex: 1; display: grid; gap: 2px; }
.task-status-label { flex: 0 0 auto; padding: 4px 8px; border: 1px solid var(--app-border); border-radius: 999px; color: var(--app-text-secondary); font-size: 10px; }
.task-delete { flex: 0 0 auto; }
.task-heading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.task-heading small { display: -webkit-box; overflow: hidden; color: var(--app-text-muted); font-size: 11px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.task-heading .task-model { width: fit-content; max-width: 100%; padding: 1px 6px; border-radius: 999px; background: var(--app-surface-muted); color: var(--app-text-secondary); font-size: 10px; -webkit-line-clamp: 1; }
.task-section small, .task-current small { color: var(--app-text-muted); font-size: 12px; line-height: 1.5; }
.task-current { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; padding: 12px; border: 1px solid var(--app-border); border-radius: 13px; }
.task-current > span:last-child { display: grid; gap: 3px; }
.status-dot { width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: var(--app-text-muted); }
.dot-running { background: var(--app-text); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-text) 10%, transparent); }
.dot-succeeded { background: var(--app-success); }
.dot-failed, .dot-cancelled { background: var(--app-error); }
.task-section { display: grid; gap: 9px; }
.task-section h4 { margin: 0; font-size: 12px; }
.progress-report-list { display: grid; gap: 9px; }
.progress-report-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 9px; align-items: start; }
.progress-report-item > span:nth-child(2) { display: grid; gap: 2px; }
.progress-report-item time { color: var(--app-text-muted); font-size: 10px; }
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
