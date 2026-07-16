<template>
  <div ref="markdownRootRef" class="collaboration-sidebar-content">
    <section class="collaboration-section">
      <div class="section-heading">
        <div class="section-title-line">
          <div class="section-title">{{ t('collaboration.title') }}</div>
          <n-tag size="small" :bordered="false" type="info">{{ t('collaboration.betaTag') }}</n-tag>
        </div>
        <n-button size="small" type="primary" :loading="store.saving" @click="createDefaultSession">
          {{ t('collaboration.new') }}
        </n-button>
      </div>

      <n-empty v-if="store.sessions.length === 0 && !store.loading" :description="t('collaboration.empty')" size="small" />
      <div v-else class="session-list">
        <div
          v-for="session in store.sessions"
          :key="session.collaboration_id"
          class="session-item"
          :class="{ active: store.activeSession?.collaboration_id === session.collaboration_id }"
          role="button"
          tabindex="0"
          @click="loadSession(session.collaboration_id)"
          @keydown.enter.prevent="loadSession(session.collaboration_id)"
          @keydown.space.prevent="loadSession(session.collaboration_id)"
        >
          <span class="session-title-row">
            <span class="session-title">{{ session.title }}</span>
            <n-popconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="deleteSession(session)"
            >
              <template #trigger>
                <n-button
                  size="tiny"
                  quaternary
                  circle
                  :aria-label="t('collaboration.deleteSession')"
                  @click.stop
                >
                  <template #icon>
                    <n-icon><TrashOutline /></n-icon>
                  </template>
                </n-button>
              </template>
              {{ t('collaboration.deleteSessionConfirm', { title: session.title }) }}
            </n-popconfirm>
          </span>
          <span class="session-meta">{{ approvalModeLabel(session.approval_mode) }} · {{ session.status }}</span>
        </div>
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-title">{{ t('collaboration.mainAgent') }}</div>
      <div class="control-stack">
        <n-select
          v-model:value="mainAgentDraft"
          size="small"
          :options="mainAgentOptions"
          :placeholder="t('collaboration.mainAgent')"
          @update:value="updateMainAgent"
        />
        <n-radio-group
          v-model:value="approvalModeDraft"
          size="small"
          class="soft-segmented-control"
          @update:value="updateApprovalMode"
        >
          <n-radio-button value="user_controlled">{{ t('collaboration.userApproval') }}</n-radio-button>
          <n-radio-button value="main_agent_delegated">{{ t('collaboration.agentApproval') }}</n-radio-button>
        </n-radio-group>
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-heading">
        <div>
          <div class="section-title">{{ t('collaboration.acceptanceWorkspace') }}</div>
          <div class="section-desc">{{ t('collaboration.acceptanceHint') }}</div>
        </div>
      </div>

      <div class="workspace-block">
        <div class="workspace-block-title">{{ t('collaboration.acceptanceFiles') }}</div>
        <div v-if="acceptancePreviewLoading && !runtimeStore.workspaceFile" class="acceptance-workspace-loading">
          <n-spin size="small" />
          <span>{{ t('workspace.readingFile') }}</span>
        </div>
        <FilePreview
          v-else-if="runtimeStore.workspaceFile"
          :file="runtimeStore.workspaceFile"
          @close="closeAcceptanceFilePreview"
        />
        <WorkspaceExplorer
          v-else-if="acceptanceWorkspaceContext"
          class="acceptance-workspace-explorer"
          :workspace-context="acceptanceWorkspaceContext"
          @select-file="handleAcceptanceFileSelect"
        />
        <n-empty v-else :description="t('collaboration.empty')" size="small" />
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-heading">
        <div class="section-title">{{ t('collaboration.activity') }}</div>
        <n-select
          v-model:value="activityAgentFilter"
          size="small"
          class="activity-filter"
          :options="activityAgentOptions"
        />
      </div>
      <n-empty v-if="filteredActivityMessages.length === 0" :description="t('collaboration.noMessages')" size="small" />
      <div v-else class="activity-list">
        <article
          v-for="message in filteredActivityMessages"
          :key="message.message_id"
          class="activity-item"
          :class="message.message_kind"
        >
          <div class="activity-head">
            <strong>{{ messageSpeaker(message) }}</strong>
            <n-tag size="tiny" :bordered="false">{{ message.message_kind }}</n-tag>
          </div>
          <div class="markdown-content sidebar-markdown activity-markdown" v-html="renderSidebarMarkdown(message.content)"></div>
        </article>
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-heading">
        <div class="section-title">{{ t('collaboration.tasks') }}</div>
        <n-button size="tiny" :loading="store.saving" @click="dispatchReadyTasks">
          {{ t('collaboration.dispatchReady') }}
        </n-button>
      </div>
      <n-empty v-if="store.tasks.length === 0" :description="t('collaboration.noTasks')" size="small" />
      <div v-else class="task-list">
        <article v-for="task in store.tasks" :key="task.task_id" class="task-card">
          <div class="task-head">
            <div class="task-title-block">
              <strong>{{ agentName(task.assignee_package_id) }}</strong>
              <div v-if="task.status === 'submitted'" class="task-review-hint">{{ t('collaboration.pendingReview') }}</div>
            </div>
            <div class="task-head-actions">
              <n-tag size="small" :type="taskStatusType(task.status)" :bordered="false">{{ task.status }}</n-tag>
              <n-button size="tiny" quaternary circle @click="toggleTaskExpanded(task.task_id)">
                <template #icon>
                  <n-icon>
                    <ChevronDownOutline v-if="isTaskExpanded(task.task_id)" />
                    <ChevronForwardOutline v-else />
                  </n-icon>
                </template>
              </n-button>
            </div>
          </div>
          <div class="markdown-content sidebar-markdown task-summary" v-html="renderSidebarMarkdown(taskSummary(task))"></div>
          <div v-if="task.depends_on?.length" class="task-meta">
            {{ t('collaboration.dependsOn') }} {{ task.depends_on.join(', ') }}
          </div>
          <div
            v-if="task.result_summary"
            class="markdown-content sidebar-markdown task-result"
            v-html="renderSidebarMarkdown(task.result_summary)"
          ></div>
          <div v-if="pendingApprovalRequests(task).length" class="task-approval-box">
            <div class="task-approval-title">{{ t('collaboration.pendingToolApproval') }}</div>
            <div
              v-for="request in pendingApprovalRequests(task)"
              :key="approvalRequestKey(request)"
              class="task-approval-request"
            >
              <strong>{{ approvalToolName(request) }}</strong>
              <span v-if="approvalRiskLabel(request)">{{ approvalRiskLabel(request) }}</span>
            </div>
            <div class="task-actions">
              <n-button size="tiny" @click="resolveTaskApproval(task, 'deny')">
                {{ t('tool.deny') }}
              </n-button>
              <n-button
                size="tiny"
                :disabled="!reviewDrafts[task.task_id]?.trim()"
                @click="resolveTaskApproval(task, 'revise')"
              >
                {{ t('tool.revise') }}
              </n-button>
              <n-button size="tiny" type="primary" @click="resolveTaskApproval(task, 'approve')">
                {{ t('tool.approve') }}
              </n-button>
            </div>
          </div>
          <div v-if="task.artifact_refs?.length" class="task-meta">
            {{ t('collaboration.reportArtifacts', { count: task.artifact_refs.length }) }}
          </div>
          <template v-if="isTaskExpanded(task.task_id)">
            <div class="markdown-content sidebar-markdown task-full-text" v-html="renderSidebarMarkdown(task.task_text)"></div>
            <div v-if="task.artifact_refs?.length" class="artifact-list">
            <button
              v-for="artifact in task.artifact_refs"
              :key="artifact.path"
              class="artifact-link"
              type="button"
              @click="openArtifact(artifact.path)"
            >
              {{ artifact.path }}
            </button>
            </div>
            <n-input
              v-model:value="reviewDrafts[task.task_id]"
              type="textarea"
              size="small"
              :autosize="{ minRows: 2, maxRows: 4 }"
              :placeholder="t('collaboration.reviewPlaceholder')"
            />
          </template>
          <div class="task-actions">
            <n-button
              size="tiny"
              :disabled="!canStartTask(task)"
              :loading="store.saving && canStartTask(task)"
              @click="startTask(task)"
            >
              {{ t('collaboration.startTask') }}
            </n-button>
            <n-button
              size="tiny"
              type="error"
              :disabled="!canCancelTask(task)"
              :loading="store.saving && canCancelTask(task)"
              @click="cancelTask(task)"
            >
              {{ t('collaboration.stopTask') }}
            </n-button>
            <n-button
              size="tiny"
              :disabled="!canOpenWorkerSession(task)"
              @click="openWorkerSession(task)"
            >
              {{ t('collaboration.openWorkerSession') }}
            </n-button>
            <n-button
              size="tiny"
              :disabled="!canRequestRevision(task)"
              @click="markTask(task, 'revision_requested')"
            >
              {{ t('collaboration.requestRevision') }}
            </n-button>
            <n-button
              size="tiny"
              type="primary"
              :disabled="task.status !== 'submitted'"
              @click="markTask(task, 'completed')"
            >
              {{ t('collaboration.accept') }}
            </n-button>
          </div>
        </article>
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-title">{{ t('collaboration.finalDelivery') }}</div>
      <n-input
        v-model:value="finalSummary"
        type="textarea"
        size="small"
        :autosize="{ minRows: 3, maxRows: 6 }"
        :placeholder="t('collaboration.finalPlaceholder')"
      />
      <div class="task-actions">
        <n-button
          size="small"
          type="primary"
          :disabled="!canCompleteSession"
          :loading="store.saving"
          @click="completeSession"
        >
          {{ t('collaboration.completeSession') }}
        </n-button>
      </div>
    </section>

    <section class="collaboration-section">
      <div class="section-title">{{ t('collaboration.members') }}</div>
      <div class="member-list">
        <div class="member-item main">
          <span>{{ t('collaboration.mainAgent') }}</span>
          <strong>{{ agentName(store.mainAgentId) }}</strong>
        </div>
        <n-empty
          v-if="store.dynamicWorkerAgents.length === 0"
          :description="t('collaboration.noDynamicWorkers')"
          size="small"
        />
        <div v-for="agent in store.dynamicWorkerAgents" :key="agent.package_id" class="member-item">
          <span>{{ t('collaboration.workerAgent') }}</span>
          <div class="member-name-row">
            <strong>{{ agent.agent_name }}</strong>
            <n-tag size="tiny" :type="workerStatusTagType(agent.package_id)" :bordered="false">
              {{ workerStatusText(agent.package_id) }}
            </n-tag>
          </div>
          <p v-if="agent.agent_description" class="member-desc">{{ agent.agent_description }}</p>
          <div class="member-meta">
            <span>{{ t('collaboration.workerTaskCount', { count: agent.task_count }) }}</span>
            <span v-if="agent.active_task_count">
              {{ t('collaboration.workerActiveTaskCount', { count: agent.active_task_count }) }}
            </span>
          </div>
          <div v-if="agent.statuses.length" class="member-statuses">
            <n-tag
              v-for="status in agent.statuses"
              :key="status"
              size="tiny"
              :type="taskStatusType(status as CollaborationTaskStatus)"
              :bordered="false"
            >
              {{ status }}
            </n-tag>
          </div>
          <div v-if="agent.session_ids.length" class="member-actions">
            <n-button size="tiny" @click="openWorkerSessionByIds(agent.package_id, agent.session_ids[0])">
              {{ t('collaboration.openWorkerSession') }}
            </n-button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NEmpty, NIcon, NInput, NPopconfirm, NRadioButton, NRadioGroup, NSelect, NSpin, NTag } from 'naive-ui'
import { SYSTEM_CHAT_PACKAGE_ID, useCollaborationStore } from '@/stores/collaboration'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import { ChevronDownOutline, ChevronForwardOutline, TrashOutline } from '@/components/icons'
import FilePreview from '@/components/workspace/FilePreview.vue'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import type {
  CollaborationApprovalMode,
  CollaborationMessageView,
  CollaborationSessionView,
  CollaborationTaskStatus,
  CollaborationTaskView,
} from '@/api/collaboration'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import type { WorkspaceEntry } from '@/types/protocol'

const store = useCollaborationStore()
const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const commands = useCommand()
const router = useRouter()
const { t } = useI18n()
const finalSummary = ref('')
const mainAgentDraft = ref(SYSTEM_CHAT_PACKAGE_ID)
const approvalModeDraft = ref<CollaborationApprovalMode>('main_agent_delegated')
const reviewDrafts = ref<Record<string, string>>({})
const acceptancePreviewLoading = ref(false)
const activityAgentFilter = ref('__all__')
const expandedTaskIds = ref<Record<string, boolean>>({})
const markdownRootRef = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(markdownRootRef)
let refreshTimer: number | null = null

const mainAgentOptions = computed(() => (
  store.agents
    .filter((agent) => agent.available_as_main)
    .map((agent) => ({ label: agent.agent_name, value: agent.package_id }))
))
const acceptanceWorkspaceContext = computed<WorkspaceRequestContext | null>(() => {
  const collaborationId = store.activeSession?.collaboration_id
  if (!collaborationId) return null
  return {
    resourceMode: 'collaboration',
    collaborationId,
  }
})
const acceptanceWorkspaceContextKey = computed(() => acceptanceWorkspaceContext.value?.collaborationId || '')
const activityMessages = computed(() => store.messages.slice(-30))
const activityAgentOptions = computed(() => {
  const options = new Map<string, string>()
  options.set('__all__', t('collaboration.activityAllAgents'))
  const mainAgentFilter = mainAgentActivityFilterValue()
  options.set(mainAgentFilter, agentName(store.activeSession?.main_agent_package_id || SYSTEM_CHAT_PACKAGE_ID))
  for (const task of store.tasks) {
    const packageId = String(task.assignee_package_id || '').trim()
    if (packageId) options.set(packageId, agentName(packageId))
  }
  for (const message of store.messages) {
    const value = messageActivityFilterValue(message)
    if (value === '__system__') {
      options.set(value, t('collaboration.systemEvents'))
    } else if (value) {
      options.set(value, agentName(value))
    }
  }
  return Array.from(options.entries()).map(([value, label]) => ({ value, label }))
})
const filteredActivityMessages = computed(() => {
  if (activityAgentFilter.value === '__all__') return activityMessages.value
  return activityMessages.value.filter((message) => messageActivityFilterValue(message) === activityAgentFilter.value)
})
const canCompleteSession = computed(() => {
  if (!store.activeSession || store.activeSession.status === 'completed') return false
  if (!finalSummary.value.trim()) return false
  return store.tasks.every((task) => ['completed', 'cancelled', 'failed'].includes(task.status))
})

onMounted(() => {
  void commands.listAgentPackageInstances()
  refreshTimer = window.setInterval(refreshActiveSession, 3000)
})

onBeforeUnmount(() => {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer)
    refreshTimer = null
  }
})

watch(
  () => store.activeSession,
  (session) => {
    mainAgentDraft.value = session?.main_agent_package_id || SYSTEM_CHAT_PACKAGE_ID
    approvalModeDraft.value = session?.approval_mode || 'main_agent_delegated'
    reviewDrafts.value = Object.fromEntries((session?.tasks || []).map((task) => [task.task_id, task.review_notes || '']))
    const nextExpanded: Record<string, boolean> = {}
    for (const task of session?.tasks || []) {
      nextExpanded[task.task_id] = expandedTaskIds.value[task.task_id] === true || pendingApprovalRequests(task).length > 0
    }
    expandedTaskIds.value = nextExpanded
    if (!activityAgentOptions.value.some((option) => option.value === activityAgentFilter.value)) {
      activityAgentFilter.value = '__all__'
    }
  },
  { immediate: true },
)

watch(
  () => acceptanceWorkspaceContextKey.value,
  () => {
    closeAcceptanceFilePreview()
  },
)

async function createDefaultSession() {
  await store.createSession({
    title: t('collaboration.defaultTitle'),
    main_agent_package_id: SYSTEM_CHAT_PACKAGE_ID,
    approval_mode: approvalModeDraft.value,
  })
}

async function loadSession(collaborationId: string) {
  await store.loadSession(collaborationId)
}

function refreshActiveSession() {
  const collaborationId = store.activeSession?.collaboration_id
  if (!collaborationId || store.loading || store.saving) return
  const hasActiveTask = store.tasks.some((task) => ['assigned', 'queued', 'accepted', 'planning', 'working'].includes(task.status))
  if (!hasActiveTask) return
  void store.loadSession(collaborationId)
}

async function deleteSession(session: CollaborationSessionView) {
  await store.deleteSession(session.collaboration_id)
}

async function updateMainAgent(value: string) {
  if (!store.activeSession) return
  await store.updateSession({
    main_agent_package_id: value || SYSTEM_CHAT_PACKAGE_ID,
    main_agent_package_session_id: null,
    main_factory_session_id: null,
  })
}

async function updateApprovalMode(value: string) {
  if (!store.activeSession) return
  await store.updateSession({ approval_mode: value as CollaborationApprovalMode })
}

async function markTask(task: CollaborationTaskView, status: CollaborationTaskStatus) {
  await store.updateTask(task, {
    status,
    review_notes: reviewDrafts.value[task.task_id] || '',
  })
}

async function startTask(task: CollaborationTaskView) {
  if (!canStartTask(task)) return
  await store.startTask(task)
}

async function openWorkerSession(task: CollaborationTaskView) {
  const packageId = String(task.assignee_package_id || '').trim()
  const sessionId = String(task.assignee_session_id || '').trim()
  await openWorkerSessionByIds(packageId, sessionId)
}

async function openWorkerSessionByIds(packageId: string, sessionId: string) {
  if (!packageId || !sessionId) return
  agentStore.enterAgentChat(packageId, sessionId)
  await router.push({ name: 'Factory' })
  await commands.selectAgentPackage(packageId, 'run')
  await commands.loadAgentPackageSession(packageId, sessionId)
}

async function cancelTask(task: CollaborationTaskView) {
  if (!canCancelTask(task)) return
  await store.cancelTask(task, reviewDrafts.value[task.task_id] || undefined)
}

async function resolveTaskApproval(task: CollaborationTaskView, action: 'approve' | 'deny' | 'revise') {
  await store.resolveTaskApproval(task, {
    action,
    revision_guidance: action === 'revise' ? reviewDrafts.value[task.task_id] || '' : undefined,
  })
}

async function dispatchReadyTasks() {
  await store.dispatchReady()
}

async function completeSession() {
  if (!canCompleteSession.value) return
  await store.completeSession(finalSummary.value.trim())
}

function handleAcceptanceFileSelect(entry: WorkspaceEntry) {
  void previewAcceptanceFile(entry.path)
}

function openArtifact(path: string) {
  void previewAcceptanceFile(path)
}

function isTaskExpanded(taskId: string): boolean {
  return expandedTaskIds.value[taskId] === true
}

function toggleTaskExpanded(taskId: string) {
  expandedTaskIds.value = {
    ...expandedTaskIds.value,
    [taskId]: !isTaskExpanded(taskId),
  }
}

function taskSummary(task: CollaborationTaskView): string {
  const result = String(task.result_summary || '').trim()
  if (result) return result
  const text = String(task.task_text || '').replace(/\s+/g, ' ').trim()
  if (!text) return t('collaboration.taskNoSummary')
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
}

function renderSidebarMarkdown(content: string | null | undefined): string {
  return renderMarkdown(String(content || ''), { surface: 'collaboration_sidebar' })
}

function mainAgentActivityFilterValue(): string {
  return String(store.activeSession?.main_agent_package_id || SYSTEM_CHAT_PACKAGE_ID).trim() || SYSTEM_CHAT_PACKAGE_ID
}

function messageActivityFilterValue(message: CollaborationMessageView): string {
  const packageId = String(message.speaker_package_id || '').trim()
  if (packageId) return packageId
  if (message.speaker_type === 'main_agent') return mainAgentActivityFilterValue()
  return '__system__'
}

async function previewAcceptanceFile(path: string) {
  acceptancePreviewLoading.value = true
  runtimeStore.workspaceFile = null
  await commands.readFile('workdir', path, acceptanceWorkspaceContext.value, 1_000_000)
  if (!runtimeStore.workspaceFile) {
    acceptancePreviewLoading.value = false
  }
}

function closeAcceptanceFilePreview() {
  acceptancePreviewLoading.value = false
  runtimeStore.workspaceFile = null
}

function canStartTask(task: CollaborationTaskView): boolean {
  return ['assigned', 'queued', 'revision_requested', 'cancelled'].includes(task.status)
}

function canCancelTask(task: CollaborationTaskView): boolean {
  return ['assigned', 'queued', 'accepted', 'planning', 'working', 'blocked', 'revision_requested'].includes(task.status)
}

function canOpenWorkerSession(task: CollaborationTaskView): boolean {
  return Boolean(String(task.assignee_package_id || '').trim() && String(task.assignee_session_id || '').trim())
}

function canRequestRevision(task: CollaborationTaskView): boolean {
  return ['submitted', 'completed'].includes(task.status)
}

function pendingApprovalRequests(task: CollaborationTaskView): Record<string, any>[] {
  const pending = task.result_payload?.pending_interrupt
  const payload = pending?.payload
  const requests = payload?.requests
  return Array.isArray(requests) ? requests.filter((item) => item && typeof item === 'object') : []
}

function approvalRequestKey(request: Record<string, any>): string {
  return String(request.tool_call_id || request.tool_name || request.tool_id || request.name || JSON.stringify(request))
}

function approvalToolName(request: Record<string, any>): string {
  return String(request.tool_name || request.tool_id || request.name || t('tool.call'))
}

function approvalRiskLabel(request: Record<string, any>): string {
  const level = String(request.risk_level || request.risk || '').trim()
  return level ? level : ''
}

function agentName(packageId: string | null | undefined): string {
  if (!packageId) return t('common.unknown')
  return store.agentById(packageId)?.agent_name || packageId
}

function isWorkerReady(packageId: string | null | undefined): boolean {
  if (!packageId) return false
  return agentStore.packageInstance(packageId)?.ready === true
}

function workerStatusText(packageId: string): string {
  const instance = agentStore.packageInstance(packageId)
  if (instance?.ready) return t('collaboration.workerReady')
  if (instance?.status) return t('collaboration.workerStatus', { status: instance.status })
  return t('collaboration.workerNotStarted')
}

function workerStatusTagType(packageId: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const instance = agentStore.packageInstance(packageId)
  if (instance?.ready) return 'success'
  if (instance?.status === 'failed' || instance?.status === 'error') return 'error'
  if (instance?.status) return 'warning'
  return 'default'
}

function approvalModeLabel(mode: CollaborationApprovalMode): string {
  return mode === 'main_agent_delegated' ? t('collaboration.agentApproval') : t('collaboration.userApproval')
}

function messageSpeaker(message: CollaborationMessageView): string {
  if (message.speaker_package_id) return agentName(message.speaker_package_id)
  if (message.speaker_type === 'main_agent') return t('collaboration.mainAgent')
  if (message.speaker_type === 'worker_agent') return t('collaboration.workerAgent')
  return message.speaker_type
}

function taskStatusType(status: CollaborationTaskStatus): 'default' | 'success' | 'warning' | 'error' | 'info' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'error'
  if (status === 'blocked' || status === 'revision_requested') return 'warning'
  if (status === 'submitted') return 'info'
  return 'default'
}
</script>

<style scoped>
.collaboration-sidebar-content {
  height: 100%;
  overflow-y: auto;
  padding: var(--app-space-lg);
}

.collaboration-section {
  padding-bottom: var(--app-space-lg);
  margin-bottom: var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.collaboration-section:last-child {
  border-bottom: 0;
  margin-bottom: 0;
}

.section-heading,
.task-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-sm);
}

.section-title {
  color: var(--app-text-strong);
  font-weight: 700;
}

.section-title-line {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-xs);
}

.section-desc,
.session-meta {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.session-list,
.control-stack,
.task-list,
.member-list {
  margin-top: var(--app-space-md);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.session-item {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--app-space-xxs);
  border: 0;
  background: transparent;
  color: var(--app-text);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  cursor: pointer;
  text-align: left;
}

.session-title-row {
  width: 100%;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-xs);
}

.session-item:hover,
.session-item.active {
  background: var(--app-surface-hover);
}

.session-title {
  min-width: 0;
  flex: 1;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.workspace-block {
  margin-top: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  overflow: hidden;
  background: var(--app-surface);
}

.workspace-block-title {
  padding: var(--app-space-sm) var(--app-space-md);
  border-bottom: 1px solid var(--app-divider);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  font-weight: 600;
}

.acceptance-workspace-explorer {
  height: 320px;
}

.acceptance-workspace-loading {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-sm);
  color: var(--app-text-muted);
  font-size: var(--app-font-sm);
}

.activity-list {
  margin-top: var(--app-space-md);
  max-height: 360px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.activity-filter {
  width: 144px;
  flex: 0 0 auto;
}

.activity-item {
  padding: var(--app-space-sm) var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.activity-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  color: var(--app-text-secondary);
  font-size: var(--app-font-xs);
}

.activity-markdown {
  margin: var(--app-space-xs) 0 0;
  color: var(--app-text);
  font-size: var(--app-font-sm);
  line-height: 1.55;
}

.activity-item.delivery {
  border-color: var(--app-border-hover);
  background: var(--app-surface-muted);
}

.task-card,
.member-item {
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.task-card p {
  margin: var(--app-space-sm) 0;
  white-space: pre-wrap;
  line-height: var(--app-leading-normal);
}

.sidebar-markdown {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
  font-size: var(--app-font-sm);
  line-height: 1.55;
}

.sidebar-markdown :deep(> :first-child) {
  margin-top: 0;
}

.sidebar-markdown :deep(> :last-child) {
  margin-bottom: 0;
}

.sidebar-markdown :deep(h1),
.sidebar-markdown :deep(h2),
.sidebar-markdown :deep(h3),
.sidebar-markdown :deep(h4) {
  margin: var(--app-space-sm) 0 var(--app-space-xs);
  font-size: var(--app-font-sm);
  line-height: 1.35;
}

.sidebar-markdown :deep(p),
.sidebar-markdown :deep(ul),
.sidebar-markdown :deep(ol),
.sidebar-markdown :deep(blockquote),
.sidebar-markdown :deep(pre),
.sidebar-markdown :deep(table) {
  margin: var(--app-space-xs) 0;
}

.sidebar-markdown :deep(table) {
  display: block;
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  font-size: var(--app-font-xs);
}

.sidebar-markdown :deep(th),
.sidebar-markdown :deep(td) {
  white-space: normal;
}

.sidebar-markdown :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
}

.task-title-block {
  min-width: 0;
}

.task-title-block strong {
  overflow-wrap: anywhere;
}

.task-head-actions {
  display: flex;
  align-items: center;
  gap: var(--app-space-xs);
  flex: 0 0 auto;
}

.task-summary {
  margin-top: var(--app-space-sm);
  color: var(--app-text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.task-review-hint {
  margin-top: var(--app-space-xxs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.task-result {
  margin: var(--app-space-sm) 0;
  color: var(--app-text-secondary);
}

.task-full-text {
  margin: var(--app-space-sm) 0;
}

.task-approval-box {
  margin: var(--app-space-sm) 0;
  padding: var(--app-space-sm);
  border: 1px solid var(--app-border-hover);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.task-approval-title {
  color: var(--app-text-strong);
  font-size: var(--app-font-sm);
  font-weight: 700;
}

.task-approval-request {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-xs);
  color: var(--app-text-secondary);
  font-size: var(--app-font-xs);
}

.task-meta {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: var(--app-space-xs) 0;
}

.artifact-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--app-primary);
  text-align: left;
  cursor: pointer;
  font-size: var(--app-font-xs);
  overflow-wrap: anywhere;
}

.task-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-sm);
}

.member-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
}

.member-item span {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.member-name-row {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
}

.member-name-row strong {
  min-width: 0;
  overflow-wrap: anywhere;
}

.member-desc {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.member-meta,
.member-statuses,
.member-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
}
</style>
