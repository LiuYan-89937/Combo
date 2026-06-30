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
import { useUiStore } from '@/stores/ui'
import type { FactoryFrontendCommand, FactoryMode } from '@/types/protocol'

export function useCommand() {
  const uiStore = useUiStore()

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

  function applyEventRequest(request: Promise<any>) {
    void request.then(applyRuntimeEvent).catch(reportError)
  }

  // ========== Session Commands ==========
  const startSession = (resumeLatest = false) => {
    sendRuntimeCommand(commands.startSessionCommand(resumeLatest))
  }

  const listSessions = () => {
    sendRuntimeCommand(commands.listSessionsCommand())
  }

  const switchSession = (sessionId: string) => {
    sendRuntimeCommand(commands.switchSessionCommand(sessionId))
  }

  const newSession = () => {
    sendRuntimeCommand(commands.newSessionCommand())
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
    applyEventRequest(agentPackagesApi.select(packageId, purpose))
  }

  const listAgentPackageSessions = (packageId: string) => {
    applyEventRequest(agentPackagesApi.sessions(packageId))
  }

  const loadAgentPackageSession = (packageId: string, sessionId: string) => {
    applyEventRequest(agentPackagesApi.session(packageId, sessionId))
  }

  const runAgentPackage = (packageId: string, message: string, sessionId?: string) => {
    const command = commands.runAgentPackageCommand(packageId, message, sessionId)
    sendRuntimeCommand(command)
    return command
  }

  // ========== Interrupt Commands ==========
  const approveToolCall = () => {
    sendRuntimeCommand(commands.resumeInterruptCommand({
      action: 'approve',
      approved: true,
    }))
  }

  const denyToolCall = () => {
    sendRuntimeCommand(commands.resumeInterruptCommand({
      action: 'deny',
      approved: false,
    }))
  }

  const trustTool = () => {
    sendRuntimeCommand(commands.resumeInterruptCommand({
      action: 'trust_tool',
      approved: true,
      trust_scope: 'tool',
    }))
  }

  const reviseWithGuidance = (guidance: string) => {
    sendRuntimeCommand(commands.resumeInterruptCommand({
      action: 'revise',
      approved: false,
      revision_guidance: guidance,
    }))
  }

  const cancelRequest = (reason = 'user_cancelled') => {
    sendRuntimeCommand(commands.cancelRuntimeRequestCommand(reason))
  }

  // ========== Workspace Commands ==========
  const refreshWorkspace = (scope: commands.WorkspaceScope, path: string, packageId?: string) => {
    applyEventRequest(workspaceApi.entries(scope, path, packageId))
  }

  const readFile = (scope: commands.WorkspaceScope, path: string, packageId?: string) => {
    applyEventRequest(workspaceApi.file(scope, path, packageId))
  }

  // ========== Knowledge Commands ==========
  const refreshKnowledge = (packageId?: string) => {
    applyEventRequest(knowledgeApi.sources(packageId))
  }

  const addKnowledgeSource = (source: commands.KnowledgeSourceInput, packageId?: string) => {
    applyEventRequest(knowledgeApi.addSource(source, packageId))
  }

  const searchKnowledge = (query: string, sourceId?: string, packageId?: string) => {
    applyEventRequest(knowledgeApi.search(query, sourceId, packageId))
  }

  // ========== Extension Commands ==========
  const refreshExtensions = (packageId?: string) => {
    applyEventRequest(extensionsApi.list(packageId))
  }

  const saveMcp = (server: commands.McpServerConfig, packageId?: string) => {
    applyEventRequest(extensionsApi.saveMcp(server, packageId))
  }

  const testMcp = (serverIdOrConfig: string | commands.McpServerConfig, packageId?: string) => {
    applyEventRequest(extensionsApi.testMcp(serverIdOrConfig, packageId))
  }

  // ========== Scheduler Commands ==========
  const refreshScheduler = () => {
    applyEventRequest(schedulerApi.jobs())
  }

  const createSchedulerJob = (job: commands.SchedulerJobInput) => {
    applyEventRequest(schedulerApi.createJob(job))
  }

  const pauseJob = (jobId: string) => {
    applyEventRequest(schedulerApi.pause(jobId))
  }

  const resumeJob = (jobId: string) => {
    applyEventRequest(schedulerApi.resume(jobId))
  }

  const deleteJob = (jobId: string) => {
    applyEventRequest(schedulerApi.delete(jobId))
  }

  const runJobNow = (jobId: string) => {
    void schedulerApi.runNow(jobId).catch(reportError)
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
    listAgentPackageSessions,
    loadAgentPackageSession,
    runAgentPackage,

    // Interrupt
    approveToolCall,
    denyToolCall,
    trustTool,
    reviseWithGuidance,
    cancelRequest,

    // Workspace
    refreshWorkspace,
    readFile,

    // Knowledge
    refreshKnowledge,
    addKnowledgeSource,
    searchKnowledge,

    // Extension
    refreshExtensions,
    saveMcp,
    testMcp,

    // Scheduler
    refreshScheduler,
    createSchedulerJob,
    pauseJob,
    resumeJob,
    deleteJob,
    runJobNow,
  }
}
