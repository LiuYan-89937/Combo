import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { ToolActivity, TranscriptItem } from '@/types/protocol'
import { isToolActivityActive, isToolActivityPendingApproval } from '@/utils/toolActivityState'

export type FactoryTimelineItem =
  | { kind: 'message'; id: string; timestamp: string; order: number; message: TranscriptItem }
  | { kind: 'tool'; id: string; timestamp: string; order: number; tool: ToolActivity }

export function useFactoryMessageProjection() {
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

  const activeStreams = computed(() => {
    return Object.values(runtimeStore.modelStreams).filter(
      (stream) => stream.visibleToUser && stream.active,
    )
  })
  const hasActiveStreams = computed(() => activeStreams.value.length > 0)
  const transcriptStreamIds = computed(() => {
    return new Set(runtimeStore.transcript.map((message) => message.streamId).filter(Boolean))
  })
  const untrackedActiveStreamMessages = computed<TranscriptItem[]>(() => {
    return activeStreams.value
      .filter((stream) => !transcriptStreamIds.value.has(stream.streamId))
      .filter(hasStreamDisplayContent)
      .map((stream) => ({
        id: stream.streamId,
        role: 'assistant',
        content: stream.content,
        timestamp: new Date().toISOString(),
        streamId: stream.streamId,
        reasoning: stream.reasoningContent
          ? {
              content: stream.reasoningContent,
              active: stream.reasoningActive,
              completedAt: stream.reasoningCompletedAt,
            }
          : undefined,
      }))
  })
  const timelineItems = computed<FactoryTimelineItem[]>(() => {
    const items: FactoryTimelineItem[] = []
    runtimeStore.transcript.forEach((message, index) => {
      items.push({
        kind: 'message',
        id: message.id,
        timestamp: message.timestamp,
        order: index,
        message,
      })
    })
    runtimeStore.tools.forEach((tool, index) => {
      items.push({
        kind: 'tool',
        id: tool.activityKey,
        timestamp: tool.createdAt || tool.timestamp,
        order: runtimeStore.transcript.length + index,
        tool,
      })
    })
    return items.sort(compareTimelineItems)
  })
  const thinkingMessages = computed<TranscriptItem[]>(() => {
    if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return []
    const activeTurn = runtimeStore.activeTurn
    if (!activeTurn?.userMessage) return []
    if (activeTurn.assistantMessages.some((message) => message.content.trim().length > 0)) return []
    if (activeStreams.value.some(hasStreamDisplayContent)) return []
    return [
      {
        id: `thinking-${activeTurn.id}`,
        role: 'assistant',
        content: '',
        timestamp: activeTurn.startedAt || new Date().toISOString(),
        metadata: {
          thinking: true,
          request_id: activeTurn.requestId,
        },
      },
    ]
  })
  const hasApprovalRequests = computed(() => runtimeStore.currentApprovalRequests.length > 0)
  const runningToolActivities = computed(() => {
    return runtimeStore.tools.filter((tool) => isToolActivityRunning(tool))
  })
  const toolActivityHint = computed(() => {
    if (!runtimeStore.hasActiveRun || runningToolActivities.value.length === 0) return ''
    if (runningToolActivities.value.some((tool) => isToolActivityPendingApproval(tool))) return t('factory.waitToolApproval')
    if (runningToolActivities.value.some((tool) => isKnowledgeRetrievalTool(tool))) return t('factory.knowledgeRetrieving')
    return runningToolActivities.value.length > 1
      ? t('factory.toolsRunning', { count: runningToolActivities.value.length })
      : t('factory.toolRunning')
  })
  const activeStreamContentKey = computed(() => {
    return [
      activeStreams.value.map((stream) => `${stream.reasoningContent || ''}${stream.content}`).join(''),
      toolActivityHint.value,
      thinkingMessages.value.length,
    ].join('')
  })

  function isMessageStreaming(streamId?: string): boolean {
    if (!streamId) return false
    return Boolean(runtimeStore.modelStreams[streamId]?.active)
  }

  return {
    activeStreamContentKey,
    hasActiveStreams,
    hasApprovalRequests,
    isMessageStreaming,
    thinkingMessages,
    timelineItems,
    toolActivityHint,
    untrackedActiveStreamMessages,
  }
}

function compareTimelineItems(left: FactoryTimelineItem, right: FactoryTimelineItem): number {
  const leftTime = Date.parse(left.timestamp)
  const rightTime = Date.parse(right.timestamp)
  const normalizedLeft = Number.isFinite(leftTime) ? leftTime : 0
  const normalizedRight = Number.isFinite(rightTime) ? rightTime : 0
  if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight
  return left.order - right.order
}

function hasStreamDisplayContent(stream: { content: string; reasoningContent?: string }): boolean {
  return stream.content.trim().length > 0 || String(stream.reasoningContent || '').trim().length > 0
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
