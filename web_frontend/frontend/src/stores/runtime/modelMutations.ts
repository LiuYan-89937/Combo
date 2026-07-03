import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  discardAssistantMessageStream,
  upsertAssistantMessageFromStream,
} from './conversationMutations'
import { isBackgroundEvent } from './eventUtils'

type ModelMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'activeRequests'
  | 'conversationTurns'
  | 'modelStreams'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function applyModelCallStarted(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  const streamId = event.payload?.stream_id
  if (!streamId) return

  state.modelStreams[streamId] = {
    streamId,
    requestId: event.request_id || null,
    nodeId: event.node_id || null,
    content: '',
    reasoningContent: '',
    reasoningActive: false,
    reasoningCompletedAt: null,
    active: true,
    completedAt: null,
    visibleToUser: event.payload?.visible_to_user !== false,
  }
}

export function applyModelReasoningDelta(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  const streamId = event.payload?.stream_id
  const delta = event.payload?.delta
  if (!streamId || delta == null) return
  const visibleToUser = event.payload?.visible_to_user !== false
  if (!visibleToUser) {
    discardAssistantMessageStream(state, streamId, event.timestamp)
    return
  }

  const stream = ensureModelStream(state, streamId, event, visibleToUser)
  stream.reasoningContent += String(delta)
  stream.reasoningActive = true
  stream.reasoningCompletedAt = null
  if (stream.visibleToUser && stream.reasoningContent) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}

export function applyModelReasoningCompleted(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  const streamId = event.payload?.stream_id
  const content = event.payload?.content ?? event.payload?.reasoning_content
  if (!streamId) return
  if (event.payload?.discard || event.payload?.visible_to_user === false) {
    discardAssistantMessageStream(state, streamId, event.timestamp)
    return
  }

  const stream = ensureModelStream(state, streamId, event, event.payload?.visible_to_user !== false)
  if (content != null) {
    stream.reasoningContent = String(content)
  }
  stream.reasoningActive = false
  stream.reasoningCompletedAt = event.timestamp
  if (stream.visibleToUser && stream.reasoningContent) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}

export function applyModelStreamDelta(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  const streamId = event.payload?.stream_id
  const delta = event.payload?.delta
  if (!streamId || delta == null) return
  const visibleToUser = event.payload?.visible_to_user !== false
  if (!visibleToUser) {
    discardAssistantMessageStream(state, streamId, event.timestamp)
    return
  }

  const target = ensureModelStream(state, streamId, event, visibleToUser)
  target.content += String(delta)
  const stream = state.modelStreams[streamId]
  if (stream.visibleToUser && (stream.content || stream.reasoningContent)) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}

export function applyModelMessageCompleted(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  if (isStoppingRequestEvent(state, event)) return
  const streamId = event.payload?.stream_id
  const content = event.payload?.content
  if (!streamId) return
  if (event.payload?.discard || event.payload?.visible_to_user === false) {
    discardAssistantMessageStream(state, streamId, event.timestamp)
    return
  }

  if (!state.modelStreams[streamId]) {
    state.modelStreams[streamId] = {
      streamId,
      requestId: event.request_id || null,
      nodeId: event.node_id || null,
      content: content || '',
      reasoningContent: String(event.payload?.reasoning_content || ''),
      reasoningActive: false,
      reasoningCompletedAt: event.payload?.reasoning_content ? event.timestamp : null,
      active: false,
      completedAt: event.timestamp,
      visibleToUser: event.payload?.visible_to_user !== false,
    }
  } else {
    state.modelStreams[streamId].requestId = state.modelStreams[streamId].requestId || event.request_id || null
    if (typeof content === 'string') {
      state.modelStreams[streamId].content = content
    }
    if (event.payload?.reasoning_content != null) {
      state.modelStreams[streamId].reasoningContent = String(event.payload.reasoning_content)
      state.modelStreams[streamId].reasoningActive = false
      state.modelStreams[streamId].reasoningCompletedAt = event.timestamp
    }
    state.modelStreams[streamId].active = false
    state.modelStreams[streamId].completedAt = event.timestamp
  }

  const stream = state.modelStreams[streamId]
  if (stream.visibleToUser && (stream.content || stream.reasoningContent)) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}

function isStoppingRequestEvent(state: ModelMutationState, event: FactoryFrontendEvent): boolean {
  const requestId = event.request_id
  if (!requestId) return false
  return Boolean(state.activeRequests[requestId]?.payload?.stop_requested_at)
}

function ensureModelStream(
  state: ModelMutationState,
  streamId: string,
  event: FactoryFrontendEvent,
  visibleToUser: boolean,
) {
  if (!state.modelStreams[streamId]) {
    state.modelStreams[streamId] = {
      streamId,
      requestId: event.request_id || null,
      nodeId: event.node_id || null,
      content: '',
      reasoningContent: '',
      reasoningActive: false,
      reasoningCompletedAt: null,
      active: true,
      completedAt: null,
      visibleToUser,
    }
  } else {
    state.modelStreams[streamId].requestId = state.modelStreams[streamId].requestId || event.request_id || null
    state.modelStreams[streamId].nodeId = state.modelStreams[streamId].nodeId || event.node_id || null
    state.modelStreams[streamId].visibleToUser = visibleToUser
    state.modelStreams[streamId].reasoningContent = state.modelStreams[streamId].reasoningContent || ''
    state.modelStreams[streamId].reasoningActive = Boolean(state.modelStreams[streamId].reasoningActive)
    state.modelStreams[streamId].reasoningCompletedAt = state.modelStreams[streamId].reasoningCompletedAt || null
  }
  return state.modelStreams[streamId]
}
