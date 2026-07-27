import { computed, nextTick, ref, watch } from 'vue'
import { collaborationApi } from '@/api/collaboration'
import { useAgentStore } from '@/stores/agent'
import { SYSTEM_CHAT_PACKAGE_ID, useCollaborationStore } from '@/stores/collaboration'
import { useRuntimeStore } from '@/stores/runtime'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useModelPoolStore } from '@/stores/modelPool'
import { isAvailableChatModelProfile } from '@/api/modelPool'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { useFactoryMessageProjection } from '@/composables/factory/useFactoryMessageProjection'
import {
  agentPackageConversationScope,
  isMoreSpecificConversationScope,
} from '@/stores/runtime/scopes'
import { messageReasoning, messageText } from '@/stores/runtime/messageParts'
import type { RuntimeAttachmentInput, TranscriptAttachmentView } from '@/types/protocol'

export function useCollaborationRuntime() {
  const collaborationStore = useCollaborationStore()
  const runtimeStore = useRuntimeStore()
  const runtimePreferences = useRuntimePreferencesStore()
  const modelPoolStore = useModelPoolStore()
  const agentStore = useAgentStore()
  const workspaceStore = useWorkspaceStore()
  const commands = useCommand()
  const messageProjection = useFactoryMessageProjection()
  const lastMainAgentRequestId = ref<string | null>(null)

  const mainAgentPackageId = computed(() => collaborationStore.mainAgentId || SYSTEM_CHAT_PACKAGE_ID)
  const mainAgentPackageSessionId = computed(() => collaborationStore.activeSession?.main_agent_package_session_id || null)
  const mainAgentConversationScope = computed(() => (
    agentPackageConversationScope(mainAgentPackageId.value, mainAgentPackageSessionId.value, {
      collaborationId: collaborationStore.activeSession?.collaboration_id,
    })
  ))
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
    !modelPoolStore.profiles.some(isAvailableChatModelProfile) ||
    runtimeStore.isInputLocked ||
    runtimeStore.isPublishConfirmationPending
  ))

  function enterActiveMainAgentContext(): void {
    const packageId = mainAgentPackageId.value
    const collaborationId = collaborationStore.activeSession?.collaboration_id
    if (!collaborationId) {
      agentStore.leaveAgentChat()
      runtimeStore.showEmptyCollaborationConversation()
      workspaceStore.setScope('package')
      return
    }
    agentStore.enterAgentChat(packageId, mainAgentPackageSessionId.value)
    runtimeStore.enterCollaborationConversation(
      collaborationId,
      packageId,
      mainAgentPackageSessionId.value,
    )
    if (mainAgentPackageSessionId.value) {
      commands.loadAgentPackageSession(
        packageId,
        mainAgentPackageSessionId.value,
        collaborationStore.activeSession?.collaboration_id,
      )
    } else {
      runtimeStore.showEmptyAgentPackageSession(packageId, collaborationId)
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
      ...(runtimePreferences.mainModelProfileId
        ? { mainModelProfileId: runtimePreferences.mainModelProfileId }
        : {}),
      ...(typeof runtimePreferences.reasoningIntensity === 'number'
        ? { reasoningIntensity: runtimePreferences.reasoningIntensity }
        : {}),
      requestTimeoutSeconds: runtimePreferences.requestTimeoutSeconds,
      maxRetries: runtimePreferences.maxRetries,
      userConfig: {
        collaboration_id: collaborationStore.activeSession.collaboration_id,
        runtime_tool_access: promptResponse.runtime_tool_access,
      },
    }
    const command = runtimeStore.isAwaitingUserInputInterrupt
      ? commands.answerInterrupt(content)
      : commands.sendAgentPackageMessage(
        packageId,
        mainAgentInput,
        mainAgentPackageSessionId.value || undefined,
        payloadAttachments,
        collaborationRuntimeOptions,
        content,
      )
    lastMainAgentRequestId.value = command.request_id || null
    runtimeStore.addUserMessage(content, command.request_id, {
      mode: 'agent_package',
      package_id: packageId,
      agent_session_id: mainAgentPackageSessionId.value,
      collaboration_id: collaborationStore.activeSession.collaboration_id,
      interrupt_resume: runtimeStore.isAwaitingUserInputInterrupt,
    }, runtimeStore.isAwaitingUserInputInterrupt ? [] : visibleAttachments)
    await rememberActiveMainAgentSession()
    return true
  }

  async function rememberActiveMainAgentSession(): Promise<void> {
    await nextTick()
    const current = collaborationStore.activeSession
    if (!current || !ownsActiveMainAgentConversation()) return
    const nextPackageSessionId = runtimeStore.activeAgentSessionId
    const payload: { main_agent_package_session_id?: string | null } = {}
    if (nextPackageSessionId && current.main_agent_package_session_id !== nextPackageSessionId) {
      payload.main_agent_package_session_id = nextPackageSessionId
    }
    if (Object.keys(payload).length === 0) return
    await collaborationStore.updateSession(payload)
  }

  function ownsActiveMainAgentConversation(): boolean {
    const expectedScope = mainAgentConversationScope.value
    const activeScope = runtimeStore.activeConversationScope
    if (!expectedScope || !activeScope) return false
    return activeScope === expectedScope || isMoreSpecificConversationScope(expectedScope, activeScope)
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
      void rememberActiveMainAgentSession().then(() => collaborationStore.loadSession(session.collaboration_id))
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
  const reasoning = messageReasoning(message)
  return {
    content: messageText(message),
    reasoning_content: reasoning?.content || '',
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
