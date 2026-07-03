import * as commands from '@/api/commands'
import { withPendingInterruptContext } from '@/composables/commands/interruptContext'
import { useRuntimeStore } from '@/stores/runtime'
import type { FactoryMode, RuntimeAttachmentInput } from '@/types/protocol'
import { useCommandTransport } from './transport'

export function useRuntimeCommands() {
  const runtimeStore = useRuntimeStore()
  const transport = useCommandTransport()

  const startSession = (resumeLatest = false, mode?: FactoryMode | null) => {
    transport.sendRuntimeCommand(commands.startSessionCommand(resumeLatest, mode))
  }

  const listSessions = () => {
    transport.sendRuntimeCommand(commands.listSessionsCommand())
  }

  const switchSession = (sessionId: string, mode?: FactoryMode | null) => {
    transport.sendRuntimeCommand(commands.switchSessionCommand(sessionId, mode))
  }

  const newSession = (mode?: FactoryMode | null) => {
    transport.sendRuntimeCommand(commands.newSessionCommand(mode))
  }

  const setMode = (mode: FactoryMode) => {
    transport.sendRuntimeCommand(commands.setModeCommand(mode))
  }

  const sendMessage = (
    message: string,
    mode?: FactoryMode,
    attachments?: RuntimeAttachmentInput[],
    runtimeOptions?: commands.RuntimeMainModelOptions,
  ) => {
    const command = commands.sendMessageCommand({ message, mode, attachments, runtimeOptions })
    transport.sendRuntimeCommand(command)
    return command
  }

  function sendInterruptDecision(payload: commands.ResumeInterruptOptions) {
    const command = commands.resumeInterruptCommand(withPendingInterruptContext(runtimeStore, payload))
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
    const command = commands.resumeInterruptCommand(withPendingInterruptContext(runtimeStore, {
      action: 'answer',
      input_text: message,
      answer: message,
      message,
    }))
    transport.sendRuntimeCommand(command)
    return command
  }

  const confirmPublish = () => {
    return sendInterruptDecision({
      action: 'answer',
      decision: 'publish',
      input_text: '发布',
      answer: '发布',
      message: '发布',
    })
  }

  const continuePublishRevision = (guidance: string) => {
    return sendInterruptDecision({
      action: 'answer',
      decision: 'message',
      input_text: guidance,
      answer: guidance,
      message: guidance,
    })
  }

  const cancelRequest = (reason = 'user_cancelled') => {
    transport.sendRuntimeCommand(commands.cancelRuntimeRequestCommand(reason))
  }

  return {
    startSession,
    listSessions,
    switchSession,
    newSession,
    setMode,
    sendMessage,
    approveToolCall,
    denyToolCall,
    trustTool,
    reviseWithGuidance,
    answerInterrupt,
    confirmPublish,
    continuePublishRevision,
    cancelRequest,
  }
}
