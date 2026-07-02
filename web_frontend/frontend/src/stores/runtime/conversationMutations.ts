import type {
  ConversationTurn,
  FactoryFrontendEvent,
  RuntimeViewState,
  ToolActivity,
  TranscriptItem,
} from '@/types/protocol'
import { toolPayloadArguments, toolPayloadValue } from './toolPayload'

type ConversationMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'conversationTurns'
  | 'modelStreams'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function ensureConversationTurn(
  state: ConversationMutationState,
  requestId: string | null,
  timestamp?: string,
): ConversationTurn {
  const existing = requestId
    ? state.conversationTurns.find((turn) => turn.requestId === requestId)
    : null
  if (existing) return existing

  const fallback = !requestId ? state.conversationTurns[state.conversationTurns.length - 1] : null
  if (fallback && fallback.status === 'running') return fallback

  const turn: ConversationTurn = {
    id: requestId || `turn-${Date.now()}`,
    requestId,
    status: state.runStatus,
    userMessage: null,
    assistantMessages: [],
    tools: [],
    startedAt: timestamp || new Date().toISOString(),
    completedAt: null,
    errorMessage: null,
  }
  state.conversationTurns.push(turn)
  return turn
}

export function upsertAssistantMessageFromStream(
  state: ConversationMutationState,
  streamId: string,
  timestamp: string,
  requestId: string | null = null,
) {
  const stream = state.modelStreams[streamId]
  if (!stream || !stream.content.trim()) return

  const existingIdx = state.transcript.findIndex((item) => item.streamId === streamId)
  let item: TranscriptItem
  if (existingIdx >= 0) {
    item = state.transcript[existingIdx]
    item.content = stream.content
    item.timestamp = timestamp
  } else {
    item = {
      id: streamId,
      role: 'assistant',
      content: stream.content,
      timestamp,
      streamId,
    }
    state.transcript.push(item)
  }

  const turn = ensureConversationTurn(state, requestId || stream.requestId || state.activeRequestId, timestamp)
  const existingMessage = turn.assistantMessages.find((message) => message.streamId === streamId)
  if (existingMessage) {
    existingMessage.content = item.content
    existingMessage.timestamp = item.timestamp
  } else {
    turn.assistantMessages.push(item)
  }
}

export function discardAssistantMessageStream(
  state: ConversationMutationState,
  streamId: string,
  timestamp: string,
) {
  const stream = state.modelStreams[streamId]
  if (stream) {
    stream.content = ''
    stream.active = false
    stream.completedAt = timestamp
    stream.visibleToUser = false
  } else {
    state.modelStreams[streamId] = {
      streamId,
      requestId: null,
      nodeId: null,
      content: '',
      active: false,
      completedAt: timestamp,
      visibleToUser: false,
    }
  }

  state.transcript = state.transcript.filter((message) => message.streamId !== streamId)
  state.conversationTurns.forEach((turn) => {
    turn.assistantMessages = turn.assistantMessages.filter((message) => message.streamId !== streamId)
  })
}

export function upsertToolActivityFromEvent(
  state: ConversationMutationState,
  event: FactoryFrontendEvent,
  status: ToolActivity['status'],
): ToolActivity | null {
  const payload = event.payload || {}
  const toolCallId = toolPayloadValue(payload, ['tool_call_id', 'toolCallId'])
  const toolName = toolPayloadValue(payload, ['tool_name', 'tool_id', 'name'])
  const activityKey = String(toolCallId || event.span_id || event.event_id)
  const existingIndex = state.tools.findIndex((item) => (
    item.activityKey === activityKey ||
    Boolean(toolCallId && item.toolCallId === String(toolCallId))
  ))
  const existing = existingIndex >= 0 ? state.tools[existingIndex] : null
  const activity: ToolActivity = {
    activityKey: existing?.activityKey || activityKey,
    requestId: event.request_id || existing?.requestId || null,
    eventType: event.event_type,
    timestamp: event.timestamp,
    createdAt: existing?.createdAt || event.timestamp,
    stageId: event.stage_id || existing?.stageId || null,
    nodeId: event.node_id || existing?.nodeId || null,
    toolCallId: toolCallId ? String(toolCallId) : existing?.toolCallId || null,
    toolName: toolName ? String(toolName) : existing?.toolName || 'tool_call',
    status,
    approvalState: existing?.approvalState || null,
    payload: {
      ...(existing?.payload || {}),
      ...payload,
      arguments: {
        ...toolPayloadArguments(existing?.payload || {}),
        ...toolPayloadArguments(payload),
      },
    },
  }

  if (existingIndex >= 0) {
    state.tools[existingIndex] = activity
  } else {
    state.tools.push(activity)
  }
  upsertTurnTool(state, activity)
  return activity
}

export function upsertTurnTool(
  state: ConversationMutationState,
  tool: ToolActivity,
) {
  const turn = ensureConversationTurn(state, tool.requestId || state.activeRequestId, tool.timestamp)
  const index = turn.tools.findIndex((item) => item.activityKey === tool.activityKey)
  if (index >= 0) {
    turn.tools[index] = { ...tool }
  } else {
    turn.tools.push({ ...tool })
  }
}
