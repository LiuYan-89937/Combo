import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { ChatMessagePart, ToolActivity, TranscriptItem } from '@/types/protocol'
import { isToolActivityActive, isToolActivityPendingApproval } from '@/utils/toolActivityState'
import { statusPart, textPart } from '@/stores/runtime/messageParts'

export type FactoryTimelineItem =
  | { kind: 'message'; id: string; timestamp: string; order: number; message: TranscriptItem }
  | { kind: 'progress'; id: string; timestamp: string; order: number; message: TranscriptItem }

export function useFactoryMessageProjection() {
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

  const activeStreams = computed(() => {
    return Object.values(runtimeStore.modelStreams).filter(
      (stream) => stream.visibleToUser && stream.active,
    )
  })
  const hasActiveStreams = computed(() => activeStreams.value.length > 0)
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
    progressMessages(runtimeStore.timeline).forEach((message, index) => {
      items.push({
        kind: 'progress',
        id: message.id,
        timestamp: message.timestamp,
        order: runtimeStore.transcript.length + index,
        message,
      })
    })
    return items.sort(compareTimelineItems)
  })
  const thinkingMessages = computed<TranscriptItem[]>(() => {
    if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return []
    const activeTurn = runtimeStore.activeTurn
    if (!activeTurn?.userMessage) return []
    if (activeTurn.assistantMessages.some(messageHasDisplayParts)) return []
    if (timelineItems.value.some(item => (
      item.kind === 'progress'
      && item.message.status === 'streaming'
      && item.message.metadata?.request_id === activeTurn.requestId
    ))) return []
    const displayStatus = activeRuntimeDisplayStatus(runtimeStore.nodes, runtimeStore.contextActivity, t)
    const statusText = displayStatus.text
    return [
      {
        id: `thinking-${activeTurn.id}`,
        role: displayStatus.role,
        content: statusText,
        timestamp: activeTurn.startedAt || new Date().toISOString(),
        status: 'streaming',
        parts: [
          textPart(`thinking-${activeTurn.id}:status`, statusText, {
            format: 'plain',
            status: 'streaming',
            timestamp: activeTurn.startedAt || new Date().toISOString(),
          }),
        ],
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
      runtimeStore.transcript.map(messagePartsKey).join('|'),
      timelineItems.value
        .filter(item => item.kind === 'progress')
        .map(item => `${item.id}:${item.message.status}:${item.message.content}`)
        .join('|'),
      toolActivityHint.value,
      thinkingMessages.value.map(message => message.content).join('|'),
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
  }
}

function progressMessages(
  timeline: ReturnType<typeof useRuntimeStore>['timeline'],
): TranscriptItem[] {
  const terminalByRequest = new Map<string, number>()
  timeline.forEach((item) => {
    if (!['run_completed', 'run_cancelled', 'run_failed'].includes(item.eventType)) return
    const requestKey = item.requestId || item.runId
    if (!requestKey) return
    terminalByRequest.set(requestKey, Math.max(
      terminalByRequest.get(requestKey) || 0,
      normalizedTimestamp(item.timestamp),
    ))
  })

  const latestByReplaceKey = new Map<string, (typeof timeline)[number]>()
  timeline.forEach((item) => {
    if (item.eventType !== 'assistant_progress') return
    const summary = String(item.payload?.summary || '').trim()
    const replaceKey = String(item.payload?.replace_key || '').trim()
    if (!summary || !replaceKey) return
    const scopeKey = item.requestId || item.runId || 'session'
    const key = `${scopeKey}:${replaceKey}`
    const previous = latestByReplaceKey.get(key)
    if (!previous || compareProcessEvents(previous, item) <= 0) {
      latestByReplaceKey.set(key, item)
    }
  })

  return Array.from(latestByReplaceKey.values()).map((item) => {
    const summary = String(item.payload.summary)
    const reportedStatus = String(item.payload.status || 'running')
    const requestKey = item.requestId || item.runId || ''
    const terminalTimestamp = requestKey ? terminalByRequest.get(requestKey) || 0 : 0
    const terminalAfterProgress = terminalTimestamp >= normalizedTimestamp(item.timestamp)
    const streaming = reportedStatus === 'running' && !terminalAfterProgress
    return {
      id: `progress-${item.id}`,
      role: 'assistant',
      content: summary,
      timestamp: item.timestamp,
      status: streaming ? 'streaming' : 'completed',
      parts: [
        statusPart(`progress-${item.id}:status`, summary, {
          status: streaming ? 'streaming' : 'completed',
          timestamp: item.timestamp,
        }),
      ],
      metadata: {
        progress: true,
        request_id: item.requestId,
        run_id: item.runId,
        source: item.payload.source,
        stage: item.payload.stage,
        progress_status: terminalAfterProgress ? 'completed' : reportedStatus,
        replace_key: item.payload.replace_key,
      },
    }
  })
}

function compareProcessEvents(
  left: ReturnType<typeof useRuntimeStore>['timeline'][number],
  right: ReturnType<typeof useRuntimeStore>['timeline'][number],
): number {
  const timeDifference = normalizedTimestamp(left.timestamp) - normalizedTimestamp(right.timestamp)
  if (timeDifference !== 0) return timeDifference
  return left.sequence - right.sequence
}

function normalizedTimestamp(timestamp: string): number {
  const value = Date.parse(timestamp)
  return Number.isFinite(value) ? value : 0
}

function activeRuntimeDisplayStatus(
  nodes: ReturnType<typeof useRuntimeStore>['nodes'],
  contextActivity: ReturnType<typeof useRuntimeStore>['contextActivity'],
  t: ReturnType<typeof useI18n>['t'],
): { text: string; role: 'assistant' | 'system' } {
  if (
    contextActivity.status === 'running'
    && contextActivity.eventType === 'context_compression_started'
  ) {
    return { text: t('context.context_compression_started'), role: 'system' }
  }
  const activeNode = Object.values(nodes)
    .filter(node => node.status === 'running' && node.payload?.visible_to_user !== false)
    .sort((left, right) => Date.parse(right.startedAt) - Date.parse(left.startedAt))[0]
  const statusKey = String(activeNode?.payload?.status_key || '')
  if (statusKey === 'runtime_initialization') {
    return { text: t('factory.status.runtimeInitialization'), role: 'system' }
  }
  if (statusKey === 'intent_analysis') {
    return { text: t('factory.status.intentAnalysis'), role: 'assistant' }
  }
  if (statusKey === 'task_analysis') {
    return { text: t('factory.status.taskAnalysis'), role: 'assistant' }
  }
  return { text: t('roles.assistantThinking'), role: 'assistant' }
}

function compareTimelineItems(left: FactoryTimelineItem, right: FactoryTimelineItem): number {
  const leftTime = Date.parse(left.timestamp)
  const rightTime = Date.parse(right.timestamp)
  const normalizedLeft = Number.isFinite(leftTime) ? leftTime : 0
  const normalizedRight = Number.isFinite(rightTime) ? rightTime : 0
  if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight
  return left.order - right.order
}

function messageHasDisplayParts(message: TranscriptItem): boolean {
  return message.parts.some(partHasDisplayContent)
}

function messagePartsKey(message: TranscriptItem): string {
  return message.parts.map((part) => {
    if (part.type === 'text' || part.type === 'reasoning') {
      return `${part.id}:${part.status || ''}:${part.text.length}`
    }
    return `${part.id}:${part.type}:${part.status || ''}`
  }).join(',')
}

function partHasDisplayContent(part: ChatMessagePart): boolean {
  if (part.type === 'text' || part.type === 'reasoning') return part.text.trim().length > 0
  return ['tool_call', 'tool_result', 'attachment', 'artifact', 'error', 'status'].includes(part.type)
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
