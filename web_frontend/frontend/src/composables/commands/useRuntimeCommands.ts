import * as commands from '@/api/commands'
import { withPendingInterruptContext } from '@/composables/commands/interruptContext'
import { useRuntimeStore } from '@/stores/runtime'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import type { FactoryMode, RuntimeAttachmentInput } from '@/types/protocol'
import { useCommandTransport } from './transport'

export function useRuntimeCommands() {
  const runtimeStore = useRuntimeStore()
  const runtimePreferences = useRuntimePreferencesStore()
  const transport = useCommandTransport()

  const startSession = (resumeLatest = false, mode?: FactoryMode | null, packageId?: string | null) => {
    transport.sendRuntimeCommand(commands.startSessionCommand(resumeLatest, mode, packageId))
  }

  const listSessions = () => {
    transport.sendRuntimeCommand(commands.listSessionsCommand())
  }

  const switchSession = (sessionId: string, mode?: FactoryMode | null, collaborationId?: string | null) => {
    if (mode === 'chat' || mode === 'create_agent' || mode === 'evolve_agent') {
      runtimeStore.expectFactorySession(sessionId, mode, collaborationId || null)
    }
    transport.sendRuntimeCommand(commands.switchSessionCommand(sessionId, mode, collaborationId))
  }

  const newSession = (
    mode?: FactoryMode | null,
    packageId?: string | null,
    collaborationId?: string | null,
  ) => {
    transport.sendRuntimeCommand(commands.newSessionCommand(mode, packageId, collaborationId))
  }

  const deleteSession = (sessionId: string, mode?: FactoryMode | null) => {
    transport.sendRuntimeCommand(commands.deleteSessionCommand(sessionId, mode))
  }

  const setMode = (mode: FactoryMode) => {
    transport.sendRuntimeCommand(commands.setModeCommand(mode))
  }

  const sendMessage = (
    message: string,
    mode?: FactoryMode,
    attachments?: RuntimeAttachmentInput[],
    runtimeOptions?: commands.RuntimeMainModelOptions,
    displayUserInput?: string | null,
  ) => {
    const command = commands.sendMessageCommand({
      message,
      sessionId: runtimeStore.activeFactorySessionId,
      mode,
      attachments,
      runtimeOptions,
      displayUserInput,
    })
    transport.sendRuntimeCommand(command)
    return command
  }

  function sendInterruptDecision(payload: commands.ResumeInterruptOptions) {
    const command = commands.resumeInterruptCommand(
      withPendingInterruptContext(runtimeStore, payload),
      runtimeStore.activeAgentSessionId || runtimeStore.activeFactorySessionId,
      {
        requestTimeoutSeconds: runtimePreferences.requestTimeoutSeconds,
        maxRetries: runtimePreferences.maxRetries,
      },
    )
    transport.sendRuntimeCommand(command)
    return command
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
    return sendInterruptDecision({
      action: 'answer',
      input_text: message,
      answer: message,
      message,
    })
  }

  const cancelRequest = (
    reason = 'user_cancelled',
    targetRequestId: string | null = null,
    visibleOutput: Record<string, any> | null = null,
  ) => {
    const activeRequest = targetRequestId ? runtimeStore.activeRequests[targetRequestId] : null
    const mode = activeRequest?.mode || runtimeStore.currentMode
    const sessionId = String(
      activeRequest?.payload?.session_id
      || (mode === 'agent_package' ? runtimeStore.activeAgentSessionId : runtimeStore.activeFactorySessionId)
      || '',
    ).trim() || null
    const packageId = String(activeRequest?.payload?.package_id || '').trim() || null
    const command = commands.cancelRuntimeRequestCommand({
      reason,
      targetRequestId,
      sessionId,
      mode,
      packageId,
      visibleOutput,
    })
    transport.sendRuntimeCommand(command)
    return command
  }

  return {
    startSession,
    listSessions,
    switchSession,
    newSession,
    deleteSession,
    setMode,
    sendMessage,
    approveToolCall,
    denyToolCall,
    trustTool,
    reviseWithGuidance,
    answerInterrupt,
    cancelRequest,
  }
}
