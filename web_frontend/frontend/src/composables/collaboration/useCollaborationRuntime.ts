import { computed, nextTick, ref, watch } from 'vue'
import { collaborationApi } from '@/api/collaboration'
import { useAgentStore } from '@/stores/agent'
import { SYSTEM_CHAT_PACKAGE_ID, useCollaborationStore } from '@/stores/collaboration'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import {
  agentPackageConversationScope,
  conversationScopeForMode,
} from '@/stores/runtime/scopes'
import type { RuntimeAttachmentInput, TranscriptAttachmentView } from '@/types/protocol'

export function useCollaborationRuntime() {
  const collaborationStore = useCollaborationStore()
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const workspaceStore = useWorkspaceStore()
  const commands = useCommand()
  const messageProjection = useFactoryMessageProjection()
  const lastMainAgentRequestId = ref<string | null>(null)

  const mainAgentPackageId = computed(() => collaborationStore.mainAgentId || SYSTEM_CHAT_PACKAGE_ID)
  const mainAgentSessionId = computed(() => collaborationStore.activeSession?.main_agent_session_id || null)
  const mainAgentConversationScope = computed(() => {
    const sessionId = mainAgentSessionId.value
    if (mainAgentPackageId.value === SYSTEM_CHAT_PACKAGE_ID) {
      return conversationScopeForMode('chat', { session_id: sessionId })
    }
    return agentPackageConversationScope(mainAgentPackageId.value, sessionId)
  })
  const mainAgentActiveRequestId = computed(() => {
    const remembered = lastMainAgentRequestId.value
    if (remembered && runtimeStore.activeRequests[remembered]?.status === 'running') {
      return remembered
    }

    const scope = mainAgentConversationScope.value
    const request = Object.values(runtimeStore.activeRequests)
      .filter((item) => item.status === 'running' && !item.background)
      .find((item) => (
        Boolean(scope && item.conversationScope === scope) ||
        Boolean(collaborationStore.activeSession?.collaboration_id && item.payload?.collaboration_id === collaborationStore.activeSession.collaboration_id)
      ))
    return request?.requestId || null
  })
  const isMainAgentRunning = computed(() => Boolean(mainAgentActiveRequestId.value))
  const inputDisabled = computed(() => (
    !collaborationStore.activeSession ||
    runtimeStore.isInputLocked ||
    runtimeStore.isPublishConfirmationPending
  ))

  function enterActiveMainAgentContext(): void {
    const packageId = mainAgentPackageId.value
    if (packageId === SYSTEM_CHAT_PACKAGE_ID) {
      agentStore.leaveAgentChat()
      runtimeStore.enterFactoryConversation('chat')
      workspaceStore.setScope('package')
      if (mainAgentSessionId.value) {
        commands.switchSession(mainAgentSessionId.value, 'chat')
      } else {
        runtimeStore.showEmptyFactoryConversation('chat')
        commands.newSession('chat')
      }
      return
    }

    agentStore.enterAgentChat(packageId, mainAgentSessionId.value)
    runtimeStore.currentMode = 'agent_package'
    if (mainAgentSessionId.value) {
      commands.loadAgentPackageSession(packageId, mainAgentSessionId.value)
    } else {
      runtimeStore.showEmptyAgentPackageSession(packageId)
      commands.selectAgentPackage(packageId)
    }
  }

  async function sendMainAgentMessage(message: string, attachments: RuntimeAttachmentInput[] = []): Promise<boolean> {
    const content = message.trim()
    if (!content || !collaborationStore.activeSession) return false

    const promptResponse = await collaborationApi.mainAgentPrompt(
      collaborationStore.activeSession.collaboration_id,
      content,
    )
    const mainAgentInput = promptResponse.prompt
    const payloadAttachments = attachments.length > 0 ? attachments : undefined
    const visibleAttachments = attachmentViews(attachments)
    const packageId = mainAgentPackageId.value
    const collaborationRuntimeOptions = {
      userConfig: {
        collaboration_id: collaborationStore.activeSession.collaboration_id,
        runtime_tool_access: {
          extra_allowed_tool_ids: ['collaboration'],
        },
      },
    }
    if (packageId === SYSTEM_CHAT_PACKAGE_ID) {
      const command = runtimeStore.isAwaitingUserInputInterrupt
        ? commands.answerInterrupt(content)
        : commands.sendMessage(mainAgentInput, 'chat', payloadAttachments, collaborationRuntimeOptions, content)
      lastMainAgentRequestId.value = command.request_id || null
      runtimeStore.addUserMessage(content, command.request_id, {
        mode: 'chat',
        package_id: SYSTEM_CHAT_PACKAGE_ID,
        collaboration_id: collaborationStore.activeSession.collaboration_id,
        interrupt_resume: runtimeStore.isAwaitingUserInputInterrupt,
      }, runtimeStore.isAwaitingUserInputInterrupt ? [] : visibleAttachments)
      await rememberActiveMainAgentSession()
      return true
    }

    const command = commands.sendAgentPackageMessage(
      packageId,
      mainAgentInput,
      mainAgentSessionId.value || undefined,
      payloadAttachments,
      collaborationRuntimeOptions,
      content,
    )
    lastMainAgentRequestId.value = command.request_id || null
    runtimeStore.addUserMessage(content, command.request_id, {
      mode: 'agent_package',
      package_id: packageId,
      agent_session_id: mainAgentSessionId.value,
      collaboration_id: collaborationStore.activeSession.collaboration_id,
    }, visibleAttachments)
    await rememberActiveMainAgentSession()
    return true
  }

  async function rememberActiveMainAgentSession(): Promise<void> {
    await nextTick()
    const nextSessionId = mainAgentPackageId.value === SYSTEM_CHAT_PACKAGE_ID
      ? runtimeStore.activeFactorySessionId
      : runtimeStore.activeAgentSessionId
    const current = collaborationStore.activeSession
    if (!current || !nextSessionId || current.main_agent_session_id === nextSessionId) return
    await collaborationStore.updateSession({ main_agent_session_id: nextSessionId })
  }

  function cancelMainAgentRequest(): void {
    const requestId = mainAgentActiveRequestId.value
    if (!requestId) return
    const visibleOutput = activeVisibleAssistantOutput(requestId)
    runtimeStore.markActiveRequestStopping(requestId)
    commands.cancelRequest('user_cancelled', requestId, visibleOutput)
  }

  watch(
    () => [
      collaborationStore.activeSession?.collaboration_id,
      collaborationStore.activeSession?.main_agent_package_id,
    ].join(':'),
    () => {
      if (collaborationStore.activeSession) enterActiveMainAgentContext()
    },
  )

  watch(
    () => [
      mainAgentPackageId.value,
      runtimeStore.activeFactorySessionId,
      runtimeStore.activeAgentSessionId,
      runtimeStore.currentMode,
    ].join(':'),
    () => {
      void rememberActiveMainAgentSession()
    },
  )

  watch(
    () => runtimeStore.runStatus,
    (status, previous) => {
      if (previous !== 'running' || status !== 'completed') return
      const session = collaborationStore.activeSession
      if (!session) return
      void collaborationStore.loadSession(session.collaboration_id)
    },
  )

  return {
    ...messageProjection,
    inputDisabled,
    isMainAgentRunning,
    cancelMainAgentRequest,
    enterActiveMainAgentContext,
    sendMainAgentMessage,
  }
}

function activeVisibleAssistantOutput(requestId: string): Record<string, any> | null {
  const runtimeStore = useRuntimeStore()
  const turn = runtimeStore.conversationTurns.find((item) => item.requestId === requestId)
  const message = turn?.assistantMessages?.[turn.assistantMessages.length - 1]
  if (!message) return null
  return {
    content: message.content || '',
    reasoning_content: message.reasoning?.content || '',
    stream_id: message.streamId || null,
  }
}

function attachmentViews(attachments: RuntimeAttachmentInput[]): TranscriptAttachmentView[] {
  return attachments.map((attachment) => ({
    kind: attachment.kind,
    name: attachment.name,
    source_kind: attachment.source_kind,
    mime_type: attachment.mime_type,
  }))
}
