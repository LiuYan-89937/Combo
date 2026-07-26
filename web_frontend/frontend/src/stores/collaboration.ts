import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  collaborationApi,
  type CollaborationAgentView,
  type CollaborationApprovalMode,
  type CollaborationRuntimeStatus,
  type CollaborationSessionView,
  type CollaborationTaskStatus,
  type CollaborationTaskView,
} from '@/api/collaboration'

export const SYSTEM_CHAT_PACKAGE_ID = 'factory_chat'
const ACTIVE_COLLABORATION_SESSION_STORAGE_KEY = 'fastagentfactory.activeCollaborationSessionId'

export interface DynamicCollaborationWorkerView {
  package_id: string
  agent_name: string
  agent_description: string
  task_count: number
  active_task_count: number
  statuses: string[]
  session_ids: string[]
  source: 'task' | 'manufacturing'
}

export const useCollaborationStore = defineStore('collaboration', () => {
  const agents = ref<CollaborationAgentView[]>([])
  const sessions = ref<CollaborationSessionView[]>([])
  const activeSession = ref<CollaborationSessionView | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const bootstrapped = ref(false)
  const error = ref<string | null>(null)

  const mainAgentId = computed(() => activeSession.value?.main_agent_package_id || SYSTEM_CHAT_PACKAGE_ID)
  const mainAgent = computed(() => agentById(mainAgentId.value))
  const workerAgents = computed(() => agents.value.filter((agent) => agent.available_as_worker))
  const messages = computed(() => activeSession.value?.messages || [])
  const tasks = computed(() => activeSession.value?.tasks || [])
  const openTasks = computed(() => tasks.value.filter((task) => !['completed', 'cancelled', 'failed'].includes(task.status)))
  const acceptanceTasks = computed(() => tasks.value.filter((task) => ['submitted', 'revision_requested', 'completed'].includes(task.status)))
  const dynamicWorkerAgents = computed<DynamicCollaborationWorkerView[]>(() => {
    const byPackageId = new Map<string, DynamicCollaborationWorkerView>()
    for (const task of tasks.value) {
      const packageId = String(task.assignee_package_id || '').trim()
      if (!packageId) continue
      const worker = ensureDynamicWorker(byPackageId, packageId, 'task')
      worker.task_count += 1
      if (!['completed', 'cancelled', 'failed'].includes(task.status)) {
        worker.active_task_count += 1
      }
      if (task.status && !worker.statuses.includes(task.status)) {
        worker.statuses.push(task.status)
      }
      const sessionId = String(task.assignee_session_id || '').trim()
      if (sessionId && !worker.session_ids.includes(sessionId)) {
        worker.session_ids.push(sessionId)
      }
    }
    for (const request of activeSession.value?.manufacturing_requests || []) {
      const packageId = String(request.result_payload?.package_id || '').trim()
      if (!packageId) continue
      const worker = ensureDynamicWorker(byPackageId, packageId, 'manufacturing')
      if (request.status && !worker.statuses.includes(request.status)) {
        worker.statuses.push(request.status)
      }
    }
    return Array.from(byPackageId.values()).sort((left, right) => {
      if (right.active_task_count !== left.active_task_count) return right.active_task_count - left.active_task_count
      return left.agent_name.localeCompare(right.agent_name)
    })
  })

  function agentById(packageId: string | null | undefined): CollaborationAgentView | null {
    if (!packageId) return null
    return agents.value.find((agent) => agent.package_id === packageId) || null
  }

  function ensureDynamicWorker(
    workers: Map<string, DynamicCollaborationWorkerView>,
    packageId: string,
    source: DynamicCollaborationWorkerView['source'],
  ): DynamicCollaborationWorkerView {
    const existing = workers.get(packageId)
    if (existing) {
      if (existing.source !== 'task') existing.source = source
      return existing
    }
    const agent = agentById(packageId)
    const worker: DynamicCollaborationWorkerView = {
      package_id: packageId,
      agent_name: agent?.agent_name || packageId,
      agent_description: agent?.agent_description || '',
      task_count: 0,
      active_task_count: 0,
      statuses: [],
      session_ids: [],
      source,
    }
    workers.set(packageId, worker)
    return worker
  }

  async function refreshAgents(): Promise<void> {
    const response = await collaborationApi.agents()
    agents.value = response.agents
  }

  async function refreshSessions(): Promise<void> {
    const response = await collaborationApi.sessions()
    sessions.value = response.sessions
    if (!activeSession.value && response.sessions.length > 0) {
      const savedId = localStorage.getItem(ACTIVE_COLLABORATION_SESSION_STORAGE_KEY)
      const nextId = savedId && response.sessions.some((session) => session.collaboration_id === savedId)
        ? savedId
        : response.sessions[0].collaboration_id
      await loadSession(nextId)
    }
  }

  async function bootstrap(): Promise<void> {
    if (bootstrapped.value || loading.value) return
    loading.value = true
    error.value = null
    try {
      await Promise.all([refreshAgents(), refreshSessions()])
      bootstrapped.value = true
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      loading.value = false
    }
  }

  async function createSession(payload: {
    title: string
    main_agent_package_id: string
    approval_mode: CollaborationApprovalMode
  }): Promise<CollaborationSessionView | null> {
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.createSession(payload)
      upsertSession(response.session)
      setActiveSession(response.session)
      return response.session
    } catch (exc) {
      error.value = errorMessage(exc)
      return null
    } finally {
      saving.value = false
    }
  }

  async function loadSession(collaborationId: string): Promise<CollaborationSessionView | null> {
    loading.value = true
    error.value = null
    try {
      const response = await collaborationApi.session(collaborationId)
      upsertSession(response.session)
      setActiveSession(response.session)
      return response.session
    } catch (exc) {
      error.value = errorMessage(exc)
      return null
    } finally {
      loading.value = false
    }
  }

  async function updateSession(payload: {
    title?: string
    main_agent_package_id?: string
    main_agent_package_session_id?: string | null
    approval_mode?: CollaborationApprovalMode
    execution_config?: CollaborationSessionView['execution_config']
    status?: CollaborationSessionView['status']
  }): Promise<CollaborationSessionView | null> {
    if (!activeSession.value) return null
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.updateSession(activeSession.value.collaboration_id, payload)
      replaceActive(response.session)
      return activeSession.value
    } catch (exc) {
      error.value = errorMessage(exc)
      return null
    } finally {
      saving.value = false
    }
  }

  async function completeSession(finalSummary: string): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.completeSession(activeSession.value.collaboration_id, {
        final_summary: finalSummary,
      })
      upsertSession(response.session)
      setActiveSession(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function addUserMessage(content: string): Promise<void> {
    if (!activeSession.value || !content.trim()) return
    const response = await collaborationApi.addMessage(activeSession.value.collaboration_id, {
      speaker_type: 'user',
      message_kind: 'chat',
      content: content.trim(),
    })
    replaceActive(response.session)
  }

  async function createTask(payload: {
    assignee_package_id: string
    task_text: string
    delivery_standard?: Record<string, any>
    visible_context?: Record<string, any>
    input_artifacts?: any[]
    depends_on?: string[]
  }): Promise<void> {
    if (!activeSession.value) return
    const response = await collaborationApi.createTask(activeSession.value.collaboration_id, payload)
    replaceActive(response.session)
  }

  async function updateTask(task: CollaborationTaskView, payload: {
    status?: CollaborationTaskStatus
    assignee_session_id?: string | null
    task_text?: string
    depends_on?: string[]
    delivery_standard?: Record<string, any>
    visible_context?: Record<string, any>
    input_artifacts?: any[]
    result_summary?: string
    review_notes?: string
    artifact_refs?: any[]
    result_payload?: Record<string, any>
  }): Promise<void> {
    if (!activeSession.value) return
    const response = await collaborationApi.updateTask(activeSession.value.collaboration_id, task.task_id, payload)
    replaceActive(response.session)
  }

  async function cancelTask(task: CollaborationTaskView, reviewNotes?: string): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.cancelTask(activeSession.value.collaboration_id, task.task_id, {
        review_notes: reviewNotes,
      })
      replaceActive(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function retryTask(task: CollaborationTaskView, retryGuidance?: string): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.retryTask(activeSession.value.collaboration_id, task.task_id, {
        retry_guidance: retryGuidance,
      })
      replaceActive(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function startTask(task: CollaborationTaskView): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.startTask(activeSession.value.collaboration_id, task.task_id)
      replaceActive(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function resolveTaskApproval(task: CollaborationTaskView, payload: {
    action: 'approve' | 'deny' | 'revise'
    revision_guidance?: string
  }): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.resolveTaskApproval(activeSession.value.collaboration_id, task.task_id, payload)
      replaceActive(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function dispatchReady(limit?: number): Promise<void> {
    if (!activeSession.value) return
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.dispatchReady(activeSession.value.collaboration_id, limit)
      replaceActive(response.session)
    } catch (exc) {
      error.value = errorMessage(exc)
    } finally {
      saving.value = false
    }
  }

  async function deleteSession(collaborationId: string): Promise<{
    main_agent_package_id?: string | null
    main_agent_package_session_id?: string | null
  } | null> {
    saving.value = true
    error.value = null
    try {
      const response = await collaborationApi.deleteSession(collaborationId)
      sessions.value = response.sessions
      if (activeSession.value?.collaboration_id === collaborationId) {
        setActiveSession(null)
        if (response.sessions[0]?.collaboration_id) {
          await loadSession(response.sessions[0].collaboration_id)
        }
      }
      return {
        main_agent_package_id: response.main_agent_package_id,
        main_agent_package_session_id: response.main_agent_package_session_id,
      }
    } catch (exc) {
      error.value = errorMessage(exc)
      return null
    } finally {
      saving.value = false
    }
  }

  function replaceActive(session: CollaborationSessionView): void {
    const current = activeSession.value?.collaboration_id === session.collaboration_id
      ? activeSession.value
      : null
    const merged = {
      ...(current || {}),
      ...session,
      statistics: session.statistics || current?.statistics,
    } as CollaborationSessionView
    upsertSession(merged)
    setActiveSession(merged)
  }

  function applySessionSnapshot(session: CollaborationSessionView): void {
    const existing = sessions.value.find(item => item.collaboration_id === session.collaboration_id)
    const merged = {
      ...(existing || {}),
      ...session,
      statistics: session.statistics || existing?.statistics,
    } as CollaborationSessionView
    upsertSession(merged)
    if (activeSession.value?.collaboration_id === session.collaboration_id) {
      activeSession.value = merged
    }
  }

  function applyRuntimeStatus(
    collaborationId: string,
    runtimeStatus: CollaborationRuntimeStatus | null,
    runtimeStatusPayload: Record<string, any>,
  ): void {
    const session = sessions.value.find((item) => item.collaboration_id === collaborationId)
    if (session) {
      session.runtime_status = runtimeStatus
      session.runtime_status_payload = runtimeStatusPayload
    }
    if (activeSession.value?.collaboration_id === collaborationId) {
      activeSession.value = {
        ...activeSession.value,
        runtime_status: runtimeStatus,
        runtime_status_payload: runtimeStatusPayload,
      }
    }
  }

  function setActiveSession(session: CollaborationSessionView | null): void {
    activeSession.value = session
    if (session?.collaboration_id) {
      localStorage.setItem(ACTIVE_COLLABORATION_SESSION_STORAGE_KEY, session.collaboration_id)
    } else {
      localStorage.removeItem(ACTIVE_COLLABORATION_SESSION_STORAGE_KEY)
    }
  }

  function upsertSession(session: CollaborationSessionView): void {
    const index = sessions.value.findIndex((item) => item.collaboration_id === session.collaboration_id)
    if (index === -1) {
      sessions.value.unshift(session)
    } else {
      sessions.value[index] = { ...sessions.value[index], ...session }
    }
    sessions.value.sort((left, right) => String(right.updated_at).localeCompare(String(left.updated_at)))
  }

  return {
    agents,
    sessions,
    activeSession,
    loading,
    saving,
    bootstrapped,
    error,
    mainAgentId,
    mainAgent,
    workerAgents,
    dynamicWorkerAgents,
    messages,
    tasks,
    openTasks,
    acceptanceTasks,
    agentById,
    bootstrap,
    refreshAgents,
    refreshSessions,
    createSession,
    loadSession,
    updateSession,
    completeSession,
    deleteSession,
    addUserMessage,
    applySessionSnapshot,
    applyRuntimeStatus,
    createTask,
    updateTask,
    cancelTask,
    retryTask,
    startTask,
    resolveTaskApproval,
    dispatchReady,
    setActiveSession,
  }
})

function errorMessage(exc: unknown): string {
  return exc instanceof Error ? exc.message : String(exc)
}
