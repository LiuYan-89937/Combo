import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  discardAssistantMessageStream,
  upsertAssistantMessageFromStream,
} from './conversationMutations'
import { isBackgroundEvent } from './eventUtils'

type ModelMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'conversationTurns'
  | 'modelStreams'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function applyModelCallStarted(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  const streamId = event.payload?.stream_id
  if (!streamId) return

  state.modelStreams[streamId] = {
    streamId,
    requestId: event.request_id || null,
    nodeId: event.node_id || null,
    content: '',
    active: true,
    completedAt: null,
    visibleToUser: event.payload?.visible_to_user !== false,
  }
}

export function applyModelStreamDelta(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  const streamId = event.payload?.stream_id
  const delta = event.payload?.delta
  if (!streamId || delta == null) return
  const visibleToUser = event.payload?.visible_to_user !== false
  if (!visibleToUser) {
    discardAssistantMessageStream(state, streamId, event.timestamp)
    return
  }

  if (!state.modelStreams[streamId]) {
    state.modelStreams[streamId] = {
      streamId,
      requestId: event.request_id || null,
      nodeId: event.node_id || null,
      content: delta,
      active: true,
      completedAt: null,
      visibleToUser,
    }
  } else {
    state.modelStreams[streamId].requestId = state.modelStreams[streamId].requestId || event.request_id || null
    state.modelStreams[streamId].nodeId = state.modelStreams[streamId].nodeId || event.node_id || null
    state.modelStreams[streamId].visibleToUser = visibleToUser
    state.modelStreams[streamId].content += delta
  }
  const stream = state.modelStreams[streamId]
  if (stream.visibleToUser && stream.content) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}

export function applyModelMessageCompleted(state: ModelMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
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
      active: false,
      completedAt: event.timestamp,
      visibleToUser: event.payload?.visible_to_user !== false,
    }
  } else {
    state.modelStreams[streamId].requestId = state.modelStreams[streamId].requestId || event.request_id || null
    if (content && content.length > state.modelStreams[streamId].content.length) {
      state.modelStreams[streamId].content = content
    }
    state.modelStreams[streamId].active = false
    state.modelStreams[streamId].completedAt = event.timestamp
  }

  const stream = state.modelStreams[streamId]
  if (stream.visibleToUser && stream.content) {
    upsertAssistantMessageFromStream(state, streamId, event.timestamp, event.request_id || stream.requestId || null)
  }
}
