import type { ChatMessagePart, FactoryFrontendEvent, RuntimeViewState, TranscriptItem } from '@/types/protocol'
import { ensureConversationTurn } from './conversationMutations'
import {
  messageReasoning,
  partsToText,
  reasoningPart,
  textPart,
  upsertPart,
} from './messageParts'
import { isBackgroundEvent } from './eventUtils'

type MessageMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'activeRequests'
  | 'conversationTurns'
  | 'modelStreams'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function applyMessageStarted(state: MessageMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
}

export function applyMessagePartDelta(state: MessageMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  if (hasAuthoritativeAssistantSnapshot(state, event)) return
  const messageId = messageIdFromEvent(event)
  const partId = partIdFromEvent(event)
  const partType = String(event.payload?.part_type || '')
  const delta = String(event.payload?.delta || '')
  if (!messageId || !partId || !partType || !delta) return
  const message = ensureMessage(state, event, messageId)
  const existing = message.parts.find((part) => part.id === partId)
  const text = existing?.type === 'reasoning' || existing?.type === 'text'
    ? `${existing.text}${delta}`
    : delta
  const part = messagePartFromPayload(event, text, 'streaming')
  upsertMessagePart(message, part, event.timestamp)
  syncTurnAssistantMessage(state, message, event)
}

export function applyMessagePartCompleted(state: MessageMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  if (hasAuthoritativeAssistantSnapshot(state, event)) return
  const messageId = messageIdFromEvent(event)
  const partId = partIdFromEvent(event)
  const partType = String(event.payload?.part_type || '')
  if (!messageId || !partId || !partType) return
  const content = String(event.payload?.content ?? event.payload?.text ?? '')
  const message = ensureMessage(state, event, messageId)
  const part = messagePartFromPayload(event, content, 'completed')
  upsertMessagePart(message, part, event.timestamp)
  syncTurnAssistantMessage(state, message, event)
}

export function applyMessageCompleted(state: MessageMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (hasAuthoritativeAssistantSnapshot(state, event)) return
  const messageId = messageIdFromEvent(event)
  if (!messageId) return
  const message = ensureMessage(state, event, messageId)
  message.status = event.payload?.status === 'failed' ? 'failed' : event.payload?.status === 'stopped' ? 'stopped' : 'completed'
  message.timestamp = event.timestamp
  message.parts = message.parts.map((part) => (
    part.status === 'streaming' ? { ...part, status: 'completed', updatedAt: event.timestamp } as ChatMessagePart : part
  ))
  message.content = partsToText(message.parts)
  message.reasoning = messageReasoning(message)
  syncTurnAssistantMessage(state, message, event)
}

export function reconcileCompletedAssistantSnapshot(
  state: MessageMutationState,
  event: FactoryFrontendEvent,
) {
  const turn = ensureConversationTurn(state, event.request_id || state.activeRequestId, event.timestamp)
  const snapshot = event.payload?.message
  const snapshotParts = Array.isArray(snapshot?.parts) ? snapshot.parts : []
  const text = snapshotParts
    .filter((part: any) => part?.kind === 'text')
    .map((part: any) => String(part.text || ''))
    .filter(Boolean)
    .join('\n') || String(event.payload?.result || '')
  if (!text) return
  const messageId = String(snapshot?.message_id || `${event.run_id || event.request_id}:assistant`)
  const timestamp = String(snapshot?.created_at || event.timestamp)
  const streamed = [...state.transcript].reverse().find((message) => (
    messageHasVisibleAssistantContent(message)
    && messageBelongsToRuntimeEvent(message, event)
  ))
  if (streamed) {
    streamed.parts = [
      ...streamed.parts.filter(part => part.type !== 'text'),
      textPart(`${streamed.id}:text`, text, {
        format: 'markdown',
        status: 'completed',
        timestamp,
      }),
    ]
    streamed.content = partsToText(streamed.parts)
    streamed.reasoning = messageReasoning(streamed)
    streamed.timestamp = timestamp
    streamed.status = 'completed'
    streamed.metadata = {
      ...(streamed.metadata || {}),
      request_id: event.request_id,
      runtime_instance_id: event.run_id,
      authoritative_snapshot: true,
    }
    if (!turn.assistantMessages.some(item => item.id === streamed.id)) {
      turn.assistantMessages.push(streamed)
    }
    return
  }
  if (turn.assistantMessages.some(messageHasVisibleAssistantContent)) return
  const message: TranscriptItem = {
    id: messageId,
    role: 'assistant',
    content: text,
    timestamp,
    status: 'completed',
    parts: [
      textPart(`${messageId}:text`, text, {
        format: 'markdown',
        status: 'completed',
        timestamp,
      }),
    ],
    streamId: messageId,
    metadata: {
      request_id: event.request_id,
      runtime_instance_id: event.run_id,
      message_protocol: 'parts',
      authoritative_snapshot: true,
    },
  }
  state.transcript.push(message)
  turn.assistantMessages.push(message)
}

export function reconcileAssistantDialogueInterrupt(
  state: MessageMutationState,
  event: FactoryFrontendEvent,
  text: string,
): boolean {
  if (event.payload?.presentation !== 'assistant_dialogue' || !text) return false
  const requestId = event.request_id || state.activeRequestId
  if (!requestId) return false
  const turn = [...state.conversationTurns]
    .reverse()
    .find(item => item.requestId === requestId)
  const message = [...(turn?.assistantMessages || [])]
    .reverse()
    .find(item => item.role === 'assistant' && !item.metadata?.tool_activity && !item.metadata?.interrupt)
  if (!message) return false

  replaceAssistantDialogueBody(message, event, text)
  const transcriptMessage = state.transcript.find(item => item.id === message.id)
  if (transcriptMessage && transcriptMessage !== message) {
    replaceAssistantDialogueBody(transcriptMessage, event, text)
  }
  return true
}

function ensureMessage(
  state: MessageMutationState,
  event: FactoryFrontendEvent,
  messageId: string,
): TranscriptItem {
  const existing = state.transcript.find((item) => item.id === messageId)
  if (existing) return existing
  const turn = ensureConversationTurn(state, event.request_id || state.activeRequestId, event.timestamp)
  const message: TranscriptItem = {
    id: messageId,
    role: event.payload?.role === 'user' || event.payload?.role === 'system' ? event.payload.role : 'assistant',
    content: '',
    timestamp: event.timestamp,
    status: 'streaming',
    parts: [],
    streamId: event.payload?.stream_id || messageId,
    metadata: {
      ...(turn.metadata || {}),
      request_id: event.request_id,
      runtime_instance_id: event.run_id,
      node_id: event.node_id,
      message_protocol: 'parts',
    },
  }
  state.transcript.push(message)
  return message
}

function replaceAssistantDialogueBody(
  message: TranscriptItem,
  event: FactoryFrontendEvent,
  text: string,
) {
  const preservedParts = message.parts.filter(part => part.type !== 'text')
  message.parts = [
    ...preservedParts,
    textPart(`${event.event_id}:text`, text, {
      format: 'markdown',
      status: 'completed',
      timestamp: event.timestamp,
    }),
  ]
  message.content = partsToText(message.parts)
  message.reasoning = messageReasoning(message)
  message.status = 'completed'
  message.timestamp = event.timestamp
  message.metadata = {
    ...(message.metadata || {}),
    interrupt: true,
    interrupt_type: String(event.payload?.type || ''),
    mode: event.mode || null,
  }
}

function upsertMessagePart(message: TranscriptItem, part: ChatMessagePart, timestamp: string) {
  message.parts = upsertPart(message.parts, part)
  message.content = partsToText(message.parts)
  message.reasoning = messageReasoning(message)
  message.status = message.parts.some((item) => item.status === 'streaming') ? 'streaming' : 'completed'
  message.timestamp = timestamp
}

function messagePartFromPayload(
  event: FactoryFrontendEvent,
  text: string,
  status: 'streaming' | 'completed',
): ChatMessagePart {
  const partId = partIdFromEvent(event) as string
  const partType = String(event.payload?.part_type || '')
  if (partType === 'reasoning') {
    return reasoningPart(partId, text, { status, timestamp: event.timestamp })
  }
  return textPart(partId, text, {
    format: event.payload?.format === 'plain' ? 'plain' : 'markdown',
    status,
    timestamp: event.timestamp,
  })
}

function syncTurnAssistantMessage(
  state: MessageMutationState,
  message: TranscriptItem,
  event: FactoryFrontendEvent,
) {
  const turn = ensureConversationTurn(state, event.request_id || state.activeRequestId, event.timestamp)
  const existing = turn.assistantMessages.find((item) => item.id === message.id)
  if (existing) {
    existing.parts = message.parts
    existing.content = message.content
    existing.reasoning = message.reasoning
    existing.timestamp = message.timestamp
    existing.status = message.status
    return
  }
  turn.assistantMessages.push(message)
}

function messageHasVisibleAssistantContent(message: TranscriptItem): boolean {
  if (message.role !== 'assistant' || message.metadata?.tool_activity) return false
  return message.parts.some((part) => (
    (part.type === 'text' || part.type === 'reasoning') && part.text.trim().length > 0
  ))
}

function hasAuthoritativeAssistantSnapshot(
  state: MessageMutationState,
  event: FactoryFrontendEvent,
): boolean {
  return state.transcript.some(message => (
    message.role === 'assistant'
    && message.metadata?.authoritative_snapshot === true
    && messageBelongsToRuntimeEvent(message, event)
  ))
}

function messageBelongsToRuntimeEvent(
  message: TranscriptItem,
  event: FactoryFrontendEvent,
): boolean {
  const runtimeInstanceId = String(event.run_id || '').trim()
  const messageRuntimeInstanceId = String(message.metadata?.runtime_instance_id || '').trim()
  if (runtimeInstanceId && messageRuntimeInstanceId) {
    return runtimeInstanceId === messageRuntimeInstanceId
  }
  const requestId = String(event.request_id || '').trim()
  const messageRequestId = String(message.metadata?.request_id || '').trim()
  return Boolean(requestId && messageRequestId && requestId === messageRequestId)
}

function messageIdFromEvent(event: FactoryFrontendEvent): string {
  return String(event.payload?.message_id || event.payload?.stream_id || '').trim()
}

function partIdFromEvent(event: FactoryFrontendEvent): string {
  return String(event.payload?.part_id || '').trim()
}

function isStoppingRequestEvent(state: MessageMutationState, event: FactoryFrontendEvent): boolean {
  const requestId = event.request_id
  if (!requestId) return false
  return Boolean(state.activeRequests[requestId]?.payload?.stop_requested_at)
}
