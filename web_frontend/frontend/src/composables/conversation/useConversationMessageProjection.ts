import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { ToolActivity, TranscriptItem } from '@/types/protocol'
import { isToolActivityActive, isToolActivityPendingApproval } from '@/utils/toolActivityState'
import { conversationVisibleParts } from '@/utils/toolPresentation'

export type ConversationTimelineItem =
  | { kind: 'message'; id: string; timestamp: string; order: number; message: TranscriptItem; messages: TranscriptItem[] }

export interface ConversationActivitySummary {
  text: string
  role: 'assistant' | 'system'
  status: string
  requestId: string
}

export function useConversationMessageProjection() {
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

  const activeStreams = computed(() => {
    return Object.values(runtimeStore.modelStreams).filter(
      (stream) => (
        stream.visibleToUser
        && stream.active
        && requestOwnsActivePresentation(stream.requestId)
      ),
    )
  })
  const hasActiveStreams = computed(() => activeStreams.value.length > 0)
  const timelineItems = computed<ConversationTimelineItem[]>(() => {
    const items: ConversationTimelineItem[] = []
    let activeAssistantItem: ConversationTimelineItem | null = null
    runtimeStore.transcript.forEach((message, index) => {
      if (message.metadata?.dispatch_state === 'queued') return
      if (conversationVisibleParts(message.parts).length === 0) return
      const requestId = String(message.metadata?.request_id || '').trim()
      if (message.role === 'assistant' && !message.metadata?.delegated_delivery) {
        const activeRequestId = activeAssistantItem
          ? String(activeAssistantItem.message.metadata?.request_id || '').trim()
          : ''
        if (activeAssistantItem && assistantMessagesBelongTogether(activeRequestId, requestId)) {
          activeAssistantItem.messages.push(message)
          activeAssistantItem.message = message
        } else {
          activeAssistantItem = {
            kind: 'message',
            id: requestId ? assistantProjectionId(requestId) : `assistant-turn-${message.id}`,
            timestamp: message.timestamp,
            order: index,
            message,
            messages: [message],
          }
          items.push(activeAssistantItem)
        }
        return
      }
      activeAssistantItem = null
      items.push({
        kind: 'message',
        id: message.id,
        timestamp: message.timestamp,
        order: index,
        message,
        messages: [message],
      })
    })
    return items
  })
  const hasApprovalRequests = computed(() => runtimeStore.currentApprovalRequests.length > 0)
  const hasUserQuestionInterrupt = computed(() => runtimeStore.isAwaitingUserInputInterrupt)
  const runningToolActivities = computed(() => {
    return runtimeStore.tools.filter(
      (tool) => isToolActivityRunning(tool) && requestOwnsActivePresentation(tool.requestId),
    )
  })
  const toolActivityHint = computed(() => {
    if (!runtimeStore.hasActiveRun || runningToolActivities.value.length === 0) return ''
    if (runningToolActivities.value.some((tool) => isToolActivityPendingApproval(tool))) return t('conversation.waitToolApproval')
    if (runningToolActivities.value.some((tool) => isKnowledgeRetrievalTool(tool))) return t('conversation.knowledgeRetrieving')
    return runningToolActivities.value.length > 1
      ? t('conversation.toolsRunning', { count: runningToolActivities.value.length })
      : t('conversation.toolRunning')
  })
  const currentActivity = computed<ConversationActivitySummary | null>(() => {
    if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return null
    const activeTurn = runtimeStore.activeTurn
    if (!activeTurn?.userMessage || !requestOwnsActivePresentation(activeTurn.requestId)) return null
    const displayStatus = activeRuntimeDisplayStatus(
      runtimeStore.runtimeActivity,
      runtimeStore.contextActivity,
      activeTurn.requestId,
      t,
      toolActivityHint.value,
    )
    return {
      text: displayStatus.text,
      role: displayStatus.role,
      status: String(runtimeStore.runStatus || 'running'),
      requestId: String(activeTurn.requestId || ''),
    }
  })
  const activeStreamContentKey = computed(() => {
    return [
      runtimeStore.transcript.map(messagePartsKey).join('|'),
      activeStreams.value
        .map(stream => `${stream.streamId}:${stream.active}:${stream.content}:${stream.reasoningContent}`)
        .join('|'),
      toolActivityHint.value,
      currentActivity.value?.text || '',
      currentActivity.value?.status || '',
    ].join('')
  })

  function isMessageStreaming(streamId?: string): boolean {
    if (!streamId) return false
    const stream = runtimeStore.modelStreams[streamId]
    return Boolean(stream?.active && requestOwnsActivePresentation(stream.requestId))
  }

  function requestOwnsActivePresentation(requestId?: string | null): boolean {
    if (!runtimeStore.hasActiveRun || !runtimeStore.activeRequestId) return false
    if (requestId && requestId !== runtimeStore.activeRequestId) return false
    const request = runtimeStore.activeRequests[runtimeStore.activeRequestId]
    return Boolean(
      request
      && request.status === 'running'
      && !request.payload?.stop_requested_at
      && !['stopped', 'cancelled'].includes(String(request.payload?.dispatch_state || '')),
    )
  }

  return {
    activeStreamContentKey,
    hasActiveStreams,
    hasApprovalRequests,
    hasUserQuestionInterrupt,
    isMessageStreaming,
    currentActivity,
    timelineItems,
    toolActivityHint,
  }
}

function activeRuntimeDisplayStatus(
  runtimeActivity: ReturnType<typeof useRuntimeStore>['runtimeActivity'],
  contextActivity: ReturnType<typeof useRuntimeStore>['contextActivity'],
  activeRequestId: string | null,
  t: ReturnType<typeof useI18n>['t'],
  toolActivityHint: string,
): { text: string; role: 'assistant' | 'system' } {
  if (
    activeRequestId
    && contextActivity.requestId === activeRequestId
    && contextActivity.status === 'running'
    && contextActivity.eventType === 'context_compression_started'
  ) {
    return { text: t('context.context_compression_started'), role: 'system' }
  }
  const activitySummary = String(runtimeActivity.payload?.summary || '').trim()
  if (
    activeRequestId
    && runtimeActivity.requestId === activeRequestId
    && runtimeActivity.status === 'active'
    && activitySummary
  ) {
    return { text: activitySummary, role: 'assistant' }
  }
  return { text: toolActivityHint || t('roles.assistantThinking'), role: 'assistant' }
}

function assistantProjectionId(requestId: string): string {
  return `assistant-turn-${requestId}`
}

function assistantMessagesBelongTogether(activeRequestId: string, nextRequestId: string): boolean {
  if (activeRequestId && nextRequestId) return activeRequestId === nextRequestId
  return true
}

function messagePartsKey(message: TranscriptItem): string {
  return message.parts.map((part) => {
    if (part.type === 'text' || part.type === 'reasoning') {
      return `${part.id}:${part.status || ''}:${part.text}`
    }
    return `${part.id}:${part.type}:${part.status || ''}`
  }).join(',')
}

function isToolActivityRunning(tool: ToolActivity): boolean {
  return isToolActivityActive(tool)
}

function isKnowledgeRetrievalTool(tool: ToolActivity): boolean {
  const name = String(tool.toolName || '').toLowerCase()
  if (name !== 'knowledge') return false
  const action = String(tool.payload?.arguments?.action || '').toLowerCase()
  return !action || ['search', 'open', 'read', 'list_documents', 'describe_source', 'list_sources'].includes(action)
}
