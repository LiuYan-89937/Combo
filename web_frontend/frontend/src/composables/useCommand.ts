/**
 * useCommand Composable
 * 提供便捷的命令和 HTTP 资源操作方法。
 */

import * as commands from '@/api/commands'
import {
  agentPackagesApi,
  extensionsApi,
  knowledgeApi,
  postCommand,
  schedulerApi,
  workspaceApi,
} from '@/api/http'
import { applyRuntimeEvent } from '@/composables/useEventStream'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import type { FactoryFrontendCommand, FactoryMode } from '@/types/protocol'
import type { AgentPackageView } from '@/stores/agent'

export function useCommand() {
  const uiStore = useUiStore()
  const runtimeStore = useRuntimeStore()

  function reportError(error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    console.error('Command failed:', error)
    uiStore.addNotification({
      type: 'error',
      title: '请求失败',
      message,
      duration: 5000,
    })
  }

  function sendRuntimeCommand(command: FactoryFrontendCommand) {
    void postCommand(command).catch(reportError)
  }

  async function applyEventRequest(request: Promise<any>) {
    try {
      const event = await request
      applyRuntimeEvent(event)
      return event
    } catch (error) {
      reportError(error)
      return null
    }
  }

  // ========== Session Commands ==========
  const startSession = (resumeLatest = false, mode?: FactoryMode | null) => {
    sendRuntimeCommand(commands.startSessionCommand(resumeLatest, mode))
  }

  const listSessions = () => {
    sendRuntimeCommand(commands.listSessionsCommand())
  }

  const switchSession = (sessionId: string, mode?: FactoryMode | null) => {
    sendRuntimeCommand(commands.switchSessionCommand(sessionId, mode))
  }

  const newSession = (mode?: FactoryMode | null) => {
    sendRuntimeCommand(commands.newSessionCommand(mode))
  }

  const setMode = (mode: FactoryMode) => {
    sendRuntimeCommand(commands.setModeCommand(mode))
  }

  // ========== Message Commands ==========
  const sendMessage = (message: string, mode?: FactoryMode, attachments?: any[]) => {
    const command = commands.sendMessageCommand({ message, mode, attachments })
    sendRuntimeCommand(command)
    return command
  }

  // ========== Agent Package Commands ==========
  const listAgentPackages = () => {
    applyEventRequest(agentPackagesApi.list())
  }

  const selectAgentPackage = (packageId: string, purpose?: 'run' | 'evolution') => {
    return applyEventRequest(agentPackagesApi.select(packageId, purpose))
  }

  const deleteAgentPackage = (packageId: string) => {
    return applyEventRequest(agentPackagesApi.delete(packageId))
  }

  const exportAgentPackage = async (pkg: AgentPackageView) => {
    try {
      const response = await agentPackagesApi.exportArchive(pkg.package_id)
      const url = URL.createObjectURL(response.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = response.filename || `${pkg.agent_name || pkg.name || pkg.package_id}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      uiStore.addNotification({
        type: 'success',
        title: '导出完成',
        message: `${pkg.agent_name || pkg.name || 'Agent 包'} 已开始下载。`,
        duration: 3000,
      })
      return true
    } catch (error) {
      reportError(error)
      return false
    }
  }

  const listAgentPackageSessions = (packageId: string) => {
    return applyEventRequest(agentPackagesApi.sessions(packageId))
  }

  const listAgentPackageInstances = () => {
    return applyEventRequest(agentPackagesApi.instances())
  }

  const initializeAgentPackage = (packageId: string) => {
    return applyEventRequest(agentPackagesApi.initialize(packageId))
  }

  const shutdownAgentPackageInstance = (packageId: string) => {
    return applyEventRequest(agentPackagesApi.shutdown(packageId))
  }

  const loadAgentPackageSession = (packageId: string, sessionId: string) => {
    return applyEventRequest(agentPackagesApi.session(packageId, sessionId))
  }

  const runAgentPackage = (packageId: string, message: string, sessionId?: string) => {
    const command = commands.runAgentPackageCommand(packageId, message, sessionId)
    sendRuntimeCommand(command)
    return command
  }

  const sendAgentPackageMessage = (packageId: string, message: string, sessionId?: string) => {
    const command = commands.sendAgentPackageMessageCommand(packageId, message, sessionId)
    sendRuntimeCommand(command)
    return command
  }

  // ========== Interrupt Commands ==========
  function sendInterruptDecision(payload: commands.ResumeInterruptOptions) {
    const command = commands.resumeInterruptCommand(withPendingInterruptContext(payload))
    runtimeStore.submitInterruptDecision(command.request_id, command.payload)
    sendRuntimeCommand(command)
    return command
  }

  function withPendingInterruptContext(payload: commands.ResumeInterruptOptions): commands.ResumeInterruptOptions {
    const pending = runtimeStore.pendingInterrupt
    if (!pending) return payload
    const pendingPayload = pending.payload || {}
    const originalRequest = pending.request_id ? runtimeStore.activeRequests[pending.request_id] : null
    const requests = Array.isArray(pendingPayload.requests) ? pendingPayload.requests : []
    const toolCallIds = requests
      .map((request: any) => String(request?.tool_call_id || '').trim())
      .filter(Boolean)
    const firstRequest = requests[0] && typeof requests[0] === 'object' ? requests[0] : {}
    const mode = pending.mode || runtimeStore.currentMode || undefined
    const runtimeSessionId = mode === 'agent_package' || mode === 'evolve_agent'
      ? pending.session_id || undefined
      : undefined
    return {
      ...payload,
      type: pendingPayload.type || 'tool_approval',
      mode,
      package_id:
        pendingPayload.package_id ||
        pendingPayload.agent_session?.package_id ||
        originalRequest?.payload?.package_id,
      session_id: runtimeSessionId,
      agent_session_id: pendingPayload.agent_session?.session_id || (mode === 'agent_package' ? pending.session_id : undefined),
      frontend_session_id: pending.session_id || undefined,
      interrupt_id: pendingPayload.interrupt_id || undefined,
      interrupt_event_id: pending.event_id,
      pending_request_id: pending.request_id || undefined,
      original_request_id: pending.request_id || undefined,
      tool_call_id: payload.tool_call_id || firstRequest.tool_call_id || undefined,
      tool_name: payload.tool_name || firstRequest.tool_name || firstRequest.tool_id || undefined,
      tool_call_ids: toolCallIds.length > 0 ? toolCallIds : undefined,
      requests,
    }
  }

  const approveToolCall = () => {
    return sendInterruptDecision({
      action: 'approve',
      approved: true,
    })
  }

  const denyToolCall = () => {
    return sendInterruptDecision({
      action: 'deny',
      approved: false,
    })
  }

  const trustTool = () => {
    return sendInterruptDecision({
      action: 'trust_tool',
      approved: true,
      trust_scope: 'tool',
    })
  }

  const reviseWithGuidance = (guidance: string) => {
    return sendInterruptDecision({
      action: 'revise',
      approved: false,
      revision_guidance: guidance,
    })
  }

  const answerInterrupt = (message: string) => {
    const command = commands.resumeInterruptCommand({
      action: 'answer',
      input_text: message,
      answer: message,
      message,
    })
    sendRuntimeCommand(command)
    return command
  }

  const cancelRequest = (reason = 'user_cancelled') => {
    sendRuntimeCommand(commands.cancelRuntimeRequestCommand(reason))
  }

  // ========== Workspace Commands ==========
  const refreshWorkspace = (scope: commands.WorkspaceScope, path: string, packageId?: string) => {
    return applyEventRequest(workspaceApi.entries(scope, path, packageId))
  }

  const readFile = (scope: commands.WorkspaceScope, path: string, packageId?: string) => {
    return applyEventRequest(workspaceApi.file(scope, path, packageId))
  }

  // ========== Knowledge Commands ==========
  const refreshKnowledge = (packageId?: string) => {
    return applyEventRequest(knowledgeApi.sources(packageId))
  }

  const addKnowledgeSource = (source: commands.KnowledgeSourceInput, packageId?: string) => {
    return applyEventRequest(knowledgeApi.addSource(source, packageId))
  }

  const listKnowledgeDocuments = (sourceId: string, packageId?: string) => {
    return applyEventRequest(knowledgeApi.documents(sourceId, packageId))
  }

  const searchKnowledge = (query: string, sourceId?: string, packageId?: string) => {
    return applyEventRequest(knowledgeApi.search(query, sourceId, packageId))
  }

  const removeKnowledgeSource = (sourceId: string, packageId?: string) => {
    return applyEventRequest(knowledgeApi.removeSource(sourceId, packageId))
  }

  const reindexKnowledgeSource = (sourceId: string, packageId?: string) => {
    return applyEventRequest(knowledgeApi.reindexSource(sourceId, packageId))
  }

  // ========== Extension Commands ==========
  const refreshExtensions = (packageId?: string) => {
    return applyEventRequest(extensionsApi.list(packageId))
  }

  const saveMcp = (server: commands.McpServerConfig, packageId?: string) => {
    return applyEventRequest(extensionsApi.saveMcp(server, packageId))
  }

  const testMcp = (serverIdOrConfig: string | commands.McpServerConfig, packageId?: string) => {
    return applyEventRequest(extensionsApi.testMcp(serverIdOrConfig, packageId))
  }

  const setMcpEnabled = (serverId: string, enabled: boolean, packageId?: string) => {
    return applyEventRequest(extensionsApi.setMcpEnabled(serverId, enabled, packageId))
  }

  const removeMcp = (serverId: string, packageId?: string) => {
    return applyEventRequest(extensionsApi.removeMcp(serverId, packageId))
  }

  const saveSkill = (skill: commands.SkillConfig, packageId?: string) => {
    return applyEventRequest(extensionsApi.saveSkill(skill, packageId))
  }

  const setSkillEnabled = (skillId: string, enabled: boolean, packageId?: string) => {
    return applyEventRequest(extensionsApi.setSkillEnabled(skillId, enabled, packageId))
  }

  const removeSkill = (skillId: string, packageId?: string) => {
    return applyEventRequest(extensionsApi.removeSkill(skillId, packageId))
  }

  // ========== Scheduler Commands ==========
  const refreshSchedulerOptions = (packageId?: string) => {
    return applyEventRequest(schedulerApi.options(packageId))
  }

  const refreshScheduler = (packageId?: string) => {
    return applyEventRequest(schedulerApi.jobs(packageId))
  }

  const createSchedulerJob = (job: commands.SchedulerJobInput, packageId?: string) => {
    return applyEventRequest(schedulerApi.createJob(job, packageId))
  }

  const pauseJob = (jobId: string, packageId?: string) => {
    return applyEventRequest(schedulerApi.pause(jobId, packageId))
  }

  const resumeJob = (jobId: string, packageId?: string) => {
    return applyEventRequest(schedulerApi.resume(jobId, packageId))
  }

  const deleteJob = (jobId: string, packageId?: string) => {
    return applyEventRequest(schedulerApi.delete(jobId, packageId))
  }

  const listSchedulerRuns = (jobId?: string, limit = 20, packageId?: string) => {
    return applyEventRequest(schedulerApi.runs(jobId, limit, packageId))
  }

  const runJobNow = (jobId: string, packageId?: string) => {
    void schedulerApi.runNow(jobId, packageId).catch(reportError)
  }

  return {
    // Session
    startSession,
    listSessions,
    switchSession,
    newSession,
    setMode,

    // Message
    sendMessage,

    // Agent Package
    listAgentPackages,
    selectAgentPackage,
    deleteAgentPackage,
    exportAgentPackage,
    listAgentPackageSessions,
    listAgentPackageInstances,
    initializeAgentPackage,
    shutdownAgentPackageInstance,
    loadAgentPackageSession,
    runAgentPackage,
    sendAgentPackageMessage,

    // Interrupt
    approveToolCall,
    denyToolCall,
    trustTool,
    reviseWithGuidance,
    answerInterrupt,
    cancelRequest,

    // Workspace
    refreshWorkspace,
    readFile,

    // Knowledge
    refreshKnowledge,
    addKnowledgeSource,
    listKnowledgeDocuments,
    searchKnowledge,
    removeKnowledgeSource,
    reindexKnowledgeSource,

    // Extension
    refreshExtensions,
    saveMcp,
    testMcp,
    setMcpEnabled,
    removeMcp,
    saveSkill,
    setSkillEnabled,
    removeSkill,

    // Scheduler
    refreshSchedulerOptions,
    refreshScheduler,
    createSchedulerJob,
    pauseJob,
    resumeJob,
    deleteJob,
    listSchedulerRuns,
    runJobNow,
  }
}
