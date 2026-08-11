import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  connectRuntime,
  dynamicRuntimeApi,
  type ConversationMessage,
  type ConversationSummary,
  type RuntimeConnection,
  type RuntimeEvent,
  type RuntimePolicy,
} from '@/api/dynamicRuntime'

export const useRuntimeStore = defineStore('runtime', () => {
  const connection = ref<RuntimeConnection | null>(null)
  const conversations = ref<ConversationSummary[]>([])
  const activeSessionId = ref<string | null>(null)
  const messages = ref<ConversationMessage[]>([])
  const policy = ref<RuntimePolicy | null>(null)
  const recentEvents = ref<RuntimeEvent[]>([])
  const status = ref<'idle' | 'connecting' | 'ready' | 'running' | 'error'>('idle')
  const error = ref('')
  let eventController: AbortController | null = null
  let lastEventId: string | null = null

  const activeConversation = computed(() =>
    conversations.value.find(item => item.session_id === activeSessionId.value) || null,
  )

  async function initialize(): Promise<void> {
    status.value = 'connecting'
    error.value = ''
    try {
      connection.value = await connectRuntime()
      await Promise.all([refreshConversations(), refreshPolicy()])
      if (!activeSessionId.value) {
        if (conversations.value.length) await openConversation(conversations.value[0].session_id)
        else await newConversation()
      }
      status.value = 'ready'
    } catch (reason) {
      status.value = 'error'
      error.value = errorText(reason)
      throw reason
    }
  }

  async function refreshConversations(): Promise<void> {
    const runtime = requireConnection()
    conversations.value = (await dynamicRuntimeApi.listConversations(runtime)).conversations
  }

  async function newConversation(): Promise<void> {
    const runtime = requireConnection()
    const result = await dynamicRuntimeApi.createConversation(runtime, '新对话')
    await refreshConversations()
    await openConversation(result.conversation.session_id)
  }

  async function openConversation(sessionId: string): Promise<void> {
    const runtime = requireConnection()
    eventController?.abort()
    eventController = null
    lastEventId = null
    const result = await dynamicRuntimeApi.conversation(runtime, sessionId)
    activeSessionId.value = result.conversation.session_id
    messages.value = result.messages
    recentEvents.value = []
    startEventStream()
  }

  async function refreshConversation(): Promise<void> {
    const runtime = requireConnection()
    if (!activeSessionId.value) return
    const result = await dynamicRuntimeApi.conversation(runtime, activeSessionId.value)
    messages.value = result.messages
    await refreshConversations()
  }

  async function sendMessage(content: string): Promise<void> {
    const runtime = requireConnection()
    const sessionId = activeSessionId.value
    const text = content.trim()
    if (!sessionId || !text || !policy.value) return
    status.value = 'running'
    error.value = ''
    try {
      await dynamicRuntimeApi.submitMessage(runtime, sessionId, text)
    } catch (reason) {
      status.value = 'error'
      error.value = errorText(reason)
      throw reason
    }
  }

  async function savePolicy(update: {
    modelProfileId: string
    executionPreference?: RuntimePolicy['execution_preference']
    approvalMode?: RuntimePolicy['approval_mode']
  }): Promise<void> {
    const runtime = requireConnection()
    policy.value = await dynamicRuntimeApi.savePolicy(runtime, {
      expected_revision: policy.value?.revision ?? null,
      execution_preference: update.executionPreference ?? policy.value?.execution_preference ?? 'auto',
      approval_mode: update.approvalMode ?? policy.value?.approval_mode ?? 'ask',
      model_profile_id: update.modelProfileId,
      reasoning_intensity: policy.value?.reasoning_intensity ?? null,
      request_timeout_seconds: policy.value?.request_timeout_seconds ?? 300,
      max_model_attempts: policy.value?.max_model_attempts ?? 2,
      max_parallel_temporary_agents: policy.value?.max_parallel_temporary_agents ?? 4,
      timezone: policy.value?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
    })
  }

  async function refreshPolicy(): Promise<void> {
    try {
      policy.value = await dynamicRuntimeApi.policy(requireConnection())
    } catch (reason) {
      if ((reason as { status?: number }).status === 404) {
        policy.value = null
        return
      }
      throw reason
    }
  }

  function startEventStream(): void {
    const runtime = requireConnection()
    const sessionId = activeSessionId.value
    if (!sessionId) return
    eventController = new AbortController()
    void dynamicRuntimeApi.streamEvents(
      runtime,
      sessionId,
      lastEventId,
      (event) => {
        lastEventId = event.event_id
        recentEvents.value = [...recentEvents.value.slice(-99), event]
        if (event.payload.kind === 'result' || event.payload.kind === 'runtime_completed') {
          status.value = 'ready'
          void refreshConversation()
        } else if (event.payload.kind === 'failed' || event.payload.kind === 'cancelled') {
          status.value = 'ready'
          error.value = String((event.payload.error as { user_message_key?: string } | undefined)?.user_message_key || '')
          void refreshConversation()
        }
      },
      eventController.signal,
    ).catch((reason) => {
      if (eventController?.signal.aborted) return
      status.value = 'error'
      error.value = errorText(reason)
    })
  }

  function requireConnection(): RuntimeConnection {
    if (!connection.value) throw new Error('Dynamic runtime is not connected.')
    return connection.value
  }

  return {
    conversations,
    activeSessionId,
    activeConversation,
    messages,
    policy,
    recentEvents,
    status,
    error,
    initialize,
    newConversation,
    openConversation,
    sendMessage,
    savePolicy,
  }
})

function errorText(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason)
}
