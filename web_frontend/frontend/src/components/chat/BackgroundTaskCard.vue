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
        </section>
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
import { computed, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { Bot, Collaborate, Upgrade } from '@vicons/carbon'
import { useI18n } from '@/composables/useI18n'
import { useCollaborationStore } from '@/stores/collaboration'
import type { BackgroundTaskView, CollaborationSessionView } from '@/api/collaboration'

const props = defineProps<{
  backgroundTaskId: string
  fallbackTitle?: string
}>()

const { t } = useI18n()
const store = useCollaborationStore()
const loading = ref(false)
const expanded = ref(true)
const session = computed(() => store.sessions.find(item => item.collaboration_id === props.backgroundTaskId) || null)
const metadata = computed(() => session.value?.execution_config?.background_task)
const kind = computed(() => metadata.value?.kind || 'delegate')
const kindIcon = computed(() => kind.value === 'team' ? Collaborate : kind.value === 'evolve' ? Upgrade : Bot)
const view = computed(() => buildView(session.value, props.fallbackTitle || t('backgroundTask.title')))
const terminal = computed(() => ['completed', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const phaseLabel = computed(() => t(`backgroundTask.phase.${view.value.phase}` as any))

onMounted(loadSnapshot)
watch(() => props.backgroundTaskId, loadSnapshot)
watch(terminal, isTerminal => {
  if (isTerminal) expanded.value = false
}, { immediate: true })

async function loadSnapshot() {
  if (!props.backgroundTaskId || session.value) return
  loading.value = true
  await store.fetchSessionSnapshot(props.backgroundTaskId)
  loading.value = false
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
  if (['completed', 'failed', 'cancelled'].includes(value)) return value
  if (value === 'blocked') return 'waiting_input'
  if (['submitted', 'revision_requested'].includes(value)) return 'awaiting_review'
  if (['assigned', 'queued', 'requested'].includes(value)) return 'queued'
  return 'running'
}

function buildView(session: CollaborationSessionView | null, fallbackTitle: string) {
  const task = session?.background_task
  const status = String(task?.status || 'queued')
  const participants = (task?.participants || []).map((participant, index) => {
    const packageId = String(participant.package_id || '').trim()
    const name = String(participant.name || packageId || t('backgroundTask.memberFallback'))
    return {
      key: packageId || `participant:${index}:${name}`,
      name,
      status: String(participant.status || 'queued'),
    }
  })
  const subtasks = (task?.subtasks || []).map((subtask, index) => ({
    task_id: String(subtask.task_id || `subtask:${index}`),
    task_text: String(subtask.title || t('backgroundTask.subtaskFallback')),
    assignee_package_id: String(subtask.package_id || t('backgroundTask.memberFallback')),
    status: String(subtask.status || 'queued'),
  }))
  const activities = (task?.recent_activity || []).slice(-8).reverse().map((activity, index) => ({
    message_id: String(activity.id || `activity:${index}`),
    content: String(activity.content || ''),
    created_at: activity.created_at,
  }))
  const artifacts = artifactViews(task)
  const phase = String(task?.current_phase || status)
  const pending = status === 'waiting_approval'
    ? t('backgroundTask.pendingApproval')
    : status === 'waiting_input'
      ? t('backgroundTask.pendingInput')
      : status === 'waiting_dependency'
        ? t('backgroundTask.pendingDependency')
        : task?.pending_action ? t('backgroundTask.pendingAction') : ''
  const error = String(task?.error?.message || '')
  return {
    title: task?.title || session?.title || fallbackTitle,
    status,
    phase,
    participants,
    participantCount: participants.length,
    subtasks,
    activities,
    artifacts,
    pending,
    error,
    hasDetails: participants.length > 0 || tasks.length > 0 || activities.length > 0 || artifacts.length > 0 || !!pending || !!error,
  }
}

function artifactViews(task: BackgroundTaskView | undefined): Array<{ key: string; name: string }> {
  const artifacts = new Map<string, { key: string; name: string }>()
  for (const artifact of task?.artifacts || []) {
    const key = String(artifact?.path || artifact?.id || '')
    if (key) artifacts.set(key, { key, name: String(artifact?.name || artifact?.path || key) })
  }
  return Array.from(artifacts.values())
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
.task-empty { margin: 0; padding: 12px var(--app-space-md); color: var(--app-text-muted); font-size: 11px; }
</style>
