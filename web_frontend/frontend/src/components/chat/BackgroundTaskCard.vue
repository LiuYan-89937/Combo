<template>
  <details
    class="background-task-card"
    :class="`task-state-${view.status}`"
    :open="expanded"
    @toggle="onToggle"
  >
    <summary class="task-summary">
      <span class="task-leading">
        <span class="task-mark" aria-hidden="true">
          <n-icon size="17"><component :is="kindIcon" /></n-icon>
        </span>
        <span class="task-copy">
          <strong>{{ view.title }}</strong>
          <small>{{ phaseLabel }}</small>
        </span>
      </span>
      <span class="task-trailing">
        <span v-if="view.participantCount" class="task-count">
          {{ t('backgroundTask.participants', { count: view.participantCount }) }}
        </span>
        <span class="task-status">{{ statusLabel }}</span>
        <span class="task-chevron" aria-hidden="true">⌄</span>
      </span>
    </summary>

    <div class="task-body">
      <p v-if="loading" class="task-empty">{{ t('backgroundTask.loading') }}</p>
      <template v-else>
        <section v-if="view.participants.length" class="task-section">
          <h4>{{ t('backgroundTask.members') }}</h4>
          <div class="participant-grid">
            <div v-for="participant in view.participants" :key="participant.key" class="participant-item">
              <span>{{ participant.name }}</span>
              <small>{{ taskStatusText(participant.status) }}</small>
            </div>
          </div>
        </section>

        <section v-if="view.subtasks.length" class="task-section">
          <h4>{{ t('backgroundTask.taskChain') }}</h4>
          <div class="subtask-list">
            <div v-for="task in view.subtasks" :key="task.task_id" class="subtask-item">
              <span class="status-dot" :class="`dot-${normalizeStatus(task.status)}`" />
              <span>
                <strong>{{ task.task_text }}</strong>
                <small>{{ task.assignee_package_id }} · {{ taskStatusText(task.status) }}</small>
              </span>
            </div>
          </div>
        </section>

        <section v-if="view.activities.length" class="task-section">
          <h4>{{ t('backgroundTask.activity') }}</h4>
          <div class="activity-list">
            <div v-for="activity in view.activities" :key="activity.message_id" class="activity-item">
              <span>{{ activity.content }}</span>
              <time>{{ formatTime(activity.created_at) }}</time>
            </div>
          </div>
        </section>

        <section v-if="view.artifacts.length" class="task-section">
          <h4>{{ t('backgroundTask.artifacts') }}</h4>
          <div class="artifact-list">
            <span v-for="artifact in view.artifacts" :key="artifact.key">{{ artifact.name }}</span>
          </div>
        </section>

        <section v-if="view.pending" class="task-notice task-notice-pending">
          <strong>{{ t('backgroundTask.pendingAction') }}</strong>
          <span>{{ view.pending }}</span>
          <div v-if="task?.status === 'waiting_approval'" class="task-actions">
            <n-button size="small" type="primary" :loading="submitting" @click="resolveApproval('approve')">
              {{ t('backgroundTask.approve') }}
            </n-button>
            <n-button size="small" :disabled="submitting" @click="resolveApproval('deny')">
              {{ t('backgroundTask.deny') }}
            </n-button>
          </div>
          <div v-else-if="task?.status === 'waiting_external'" class="task-response">
            <n-input v-model:value="responseText" type="textarea" :placeholder="t('backgroundTask.responsePlaceholder')" />
            <n-button size="small" type="primary" :loading="submitting" @click="resumeTask">
              {{ t('backgroundTask.submitResponse') }}
            </n-button>
          </div>
        </section>
        <p v-if="actionError" class="task-notice task-notice-error">{{ actionError }}</p>
        <section v-if="view.error" class="task-notice task-notice-error">
          <strong>{{ t('common.error') }}</strong>
          <span>{{ view.error }}</span>
        </section>
        <p v-if="!view.hasDetails" class="task-empty">{{ t('backgroundTask.noDetails') }}</p>
      </template>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NIcon, NInput } from 'naive-ui'
import { Bot, Upgrade } from '@vicons/carbon'
import { useI18n } from '@/composables/useI18n'
import {
  backgroundTasksApi,
  type BackgroundTask,
  type BackgroundTaskEvent,
} from '@/api/backgroundTasks'

const props = defineProps<{
  backgroundTaskId: string
  fallbackTitle?: string
}>()

const { t } = useI18n()
const loading = ref(false)
const submitting = ref(false)
const responseText = ref('')
const actionError = ref('')
const expanded = ref(true)
const task = ref<BackgroundTask | null>(null)
const events = ref<BackgroundTaskEvent[]>([])
let pollTimer: ReturnType<typeof setTimeout> | null = null
const kindIcon = computed(() => task.value?.type === 'evolve' ? Upgrade : Bot)
const view = computed(() => buildView(task.value, events.value, props.fallbackTitle || t('backgroundTask.title')))
const terminal = computed(() => ['succeeded', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const phaseLabel = computed(() => t(`backgroundTask.phase.${view.value.phase}` as any))

onMounted(loadSnapshot)
onBeforeUnmount(stopPolling)
watch(() => props.backgroundTaskId, () => {
  task.value = null
  events.value = []
  loadSnapshot()
})
watch(terminal, isTerminal => {
  if (isTerminal) {
    expanded.value = false
    stopPolling()
  }
}, { immediate: true })

async function loadSnapshot() {
  if (!props.backgroundTaskId) return
  loading.value = true
  actionError.value = ''
  try {
    const [taskResponse, eventResponse] = await Promise.all([
      backgroundTasksApi.get(props.backgroundTaskId),
      backgroundTasksApi.events(props.backgroundTaskId, events.value.at(-1)?.seq || 0),
    ])
    task.value = taskResponse.task
    if (eventResponse.events.length) {
      const bySequence = new Map(events.value.map(item => [item.seq, item]))
      for (const event of eventResponse.events) bySequence.set(event.seq, event)
      events.value = Array.from(bySequence.values()).sort((left, right) => left.seq - right.seq)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
  if (!terminal.value) schedulePoll()
}

function schedulePoll() {
  stopPolling()
  pollTimer = setTimeout(loadSnapshot, 1500)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

async function resolveApproval(decision: 'approve' | 'deny') {
  if (!task.value) return
  submitting.value = true
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.approve(task.value.task_id, decision)).task
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function resumeTask() {
  if (!task.value || !responseText.value.trim()) return
  submitting.value = true
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.resume(task.value.task_id, { response: responseText.value.trim() })).task
    responseText.value = ''
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

function onToggle(event: Event) {
  expanded.value = (event.currentTarget as HTMLDetailsElement).open
}

function taskStatusText(status: unknown): string {
  const normalized = normalizeStatus(status)
  return t(`backgroundTask.status.${normalized}` as any)
}

function normalizeStatus(status: unknown): string {
  const value = String(status || '')
  if (value === 'succeeded') return 'succeeded'
  if (['failed', 'cancelled', 'queued', 'waiting_approval', 'waiting_external', 'cancelling'].includes(value)) {
    return value
  }
  return 'running'
}

function buildView(task: BackgroundTask | null, events: BackgroundTaskEvent[], fallbackTitle: string) {
  const status = task?.status || 'queued'
  const packageId = String(task?.assignee_package_id || '').trim()
  const participants = packageId ? [{ key: packageId, name: packageId, status }] : []
  const subtasks = task ? [{
    task_id: task.task_id,
    task_text: task.task_text || fallbackTitle,
    assignee_package_id: packageId || task.type,
    status,
  }] : []
  const activities = events.slice(-8).reverse().map(event => ({
    message_id: event.event_id,
    content: eventLabel(event),
    created_at: event.created_at,
  }))
  const artifacts = artifactViews(task)
  const phase = status
  const pending = status === 'waiting_approval'
    ? t('backgroundTask.pendingApproval')
    : status === 'waiting_external'
      ? t('backgroundTask.pendingInput')
      : ''
  const error = String(task?.error?.message || '')
  return {
    title: task?.task_text || fallbackTitle,
    status,
    phase,
    participants,
    participantCount: participants.length,
    subtasks,
    activities,
    artifacts,
    pending,
    error,
    hasDetails: participants.length > 0 || subtasks.length > 0 || activities.length > 0 || artifacts.length > 0 || !!pending || !!error,
  }
}

function artifactViews(task: BackgroundTask | null): Array<{ key: string; name: string }> {
  const artifacts = new Map<string, { key: string; name: string }>()
  for (const artifact of task?.artifact_refs || []) {
    const key = String(artifact?.path || artifact?.id || '')
    if (key) artifacts.set(key, { key, name: String(artifact?.name || artifact?.path || key) })
  }
  return Array.from(artifacts.values())
}

function eventLabel(event: BackgroundTaskEvent): string {
  const status = String(event.payload.status || '')
  return status ? taskStatusText(status) : event.event_type.split('_').join(' ')
}

function formatTime(value: unknown): string {
  const parsed = new Date(String(value || ''))
  if (!Number.isFinite(parsed.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(parsed)
}
</script>

<style scoped>
.background-task-card {
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
}

.task-summary,
.task-leading,
.task-trailing {
  display: flex;
  align-items: center;
}

.task-summary {
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: 11px var(--app-space-md);
  cursor: pointer;
  user-select: none;
}

.task-leading { min-width: 0; gap: 10px; }
.task-trailing { flex: 0 0 auto; gap: 8px; }
.task-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text);
}
.task-copy { display: grid; min-width: 0; gap: 2px; }
.task-copy strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.task-copy small,
.task-count { color: var(--app-text-muted); font-size: 11px; }
.task-status {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  font-size: 11px;
}
.task-state-running .task-status { border-color: var(--app-info); color: var(--app-info); }
.task-state-claimed .task-status,
.task-state-waiting_approval .task-status,
.task-state-waiting_external .task-status { border-color: var(--app-info); color: var(--app-info); }
.task-state-succeeded .task-status { border-color: var(--app-success); color: var(--app-success); }
.task-state-completed .task-status { border-color: var(--app-success); color: var(--app-success); }
.task-state-failed .task-status { border-color: var(--app-error); color: var(--app-error); }
.task-chevron { transition: transform var(--app-transition-base); }
details[open] > summary .task-chevron { transform: rotate(180deg); }
.task-body { border-top: 1px solid var(--app-divider); }
.task-section { display: grid; gap: 8px; padding: 10px var(--app-space-md); border-bottom: 1px solid var(--app-divider); }
.task-section h4 { margin: 0; color: var(--app-text-muted); font-size: 11px; font-weight: 600; }
.participant-grid { display: flex; flex-wrap: wrap; gap: 7px; }
.participant-item { display: grid; gap: 1px; padding: 6px 9px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); }
.participant-item span { font-size: 12px; }
.participant-item small { color: var(--app-text-muted); font-size: 10px; }
.subtask-list,
.activity-list { display: grid; gap: 7px; }
.subtask-item { display: grid; grid-template-columns: 8px minmax(0, 1fr); align-items: start; gap: 8px; }
.subtask-item > span:last-child { display: grid; gap: 2px; }
.subtask-item strong { font-size: 12px; font-weight: 500; }
.subtask-item small { color: var(--app-text-muted); font-size: 10px; }
.status-dot { width: 6px; height: 6px; margin-top: 5px; border-radius: 50%; background: var(--app-text-subtle); }
.dot-running { background: var(--app-info); }
.dot-completed { background: var(--app-success); }
.dot-failed,
.dot-cancelled { background: var(--app-error); }
.activity-item { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; }
.activity-item span { min-width: 0; overflow-wrap: anywhere; }
.activity-item time { flex: 0 0 auto; color: var(--app-text-subtle); font-size: 10px; }
.artifact-list { display: flex; flex-wrap: wrap; gap: 6px; }
.artifact-list span { padding: 4px 8px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); font-size: 11px; }
.task-notice { display: grid; gap: 3px; padding: 9px var(--app-space-md); font-size: 11px; }
.task-notice-pending { color: var(--app-warning); }
.task-notice-error { color: var(--app-error); }
.task-actions { display: flex; gap: 8px; margin-top: 6px; }
.task-response { display: grid; gap: 8px; margin-top: 6px; }
.task-empty { margin: 0; padding: 12px var(--app-space-md); color: var(--app-text-muted); font-size: 11px; }
</style>
