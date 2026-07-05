import type { FactoryFrontendEvent, RuntimeViewState, ToolActivity } from '@/types/protocol'
import {
  upsertToolActivityFromEvent,
  upsertToolMessagePart,
  upsertTurnTool,
} from './conversationMutations'
import { isBackgroundEvent } from './eventUtils'

type ToolMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'conversationTurns'
  | 'modelStreams'
  | 'pendingInterrupt'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function applyToolLifecycleEvent(
  state: ToolMutationState,
  event: FactoryFrontendEvent,
  status: ToolActivity['status'],
) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  upsertToolActivityFromEvent(state, event, status)
}

export function applyToolApprovalRequested(state: ToolMutationState, event: FactoryFrontendEvent) {
  state.runStatus = 'interrupted'
  state.pendingInterrupt = event

  const requests = event.payload?.requests || []
  requests.forEach((req: any) => {
    const approvalEvent = {
      ...event,
      payload: { ...(event.payload || {}), ...req },
    } satisfies FactoryFrontendEvent
    const activity = upsertToolActivityFromEvent(state, approvalEvent, 'approval')
    if (activity) {
      activity.approvalState = 'pending'
      upsertTurnTool(state, activity)
    }
  })
}

export function applyToolApprovalResolved(state: ToolMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  const approved = event.payload?.approved
  const toolCallIds = approvalToolCallIds(event.payload)
  state.pendingInterrupt = null
  if (state.runStatus === 'interrupted') {
    state.runStatus = 'running'
  }

  if (toolCallIds.length > 0) {
    const matched = state.tools.filter((item) => item.toolCallId && toolCallIds.includes(item.toolCallId))
    if (matched.length > 0) {
      matched.forEach((tool) => resolveApprovalTool(tool, event, Boolean(approved)))
      matched.forEach((tool) => upsertTurnTool(state, tool))
      matched.forEach((tool) => upsertToolMessagePart(state, tool))
      return
    }
  }

  const pendingTools = state.tools.filter((tool) => tool.status === 'approval' && tool.approvalState === 'pending')
  if (pendingTools.length > 0) {
    pendingTools.forEach((tool) => resolveApprovalTool(tool, event, Boolean(approved)))
    pendingTools.forEach((tool) => upsertTurnTool(state, tool))
    pendingTools.forEach((tool) => upsertToolMessagePart(state, tool))
    return
  }

  state.tools
    .filter((tool) => tool.status === 'approval')
    .forEach((tool) => {
      resolveApprovalTool(tool, event, Boolean(approved))
      upsertTurnTool(state, tool)
      upsertToolMessagePart(state, tool)
    })
}

function resolveApprovalTool(tool: ToolActivity, event: FactoryFrontendEvent, approved: boolean) {
  tool.approvalState = approved ? 'approved' : 'rejected'
  tool.eventType = event.event_type
  tool.timestamp = event.timestamp
  tool.payload = {
    ...(tool.payload || {}),
    approval: event.payload || {},
  }
}

function approvalToolCallIds(payload: Record<string, any> | undefined): string[] {
  const values = [
    payload?.tool_call_id,
    payload?.toolCallId,
    ...(Array.isArray(payload?.tool_call_ids) ? payload.tool_call_ids : []),
    ...(Array.isArray(payload?.toolCallIds) ? payload.toolCallIds : []),
  ]
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)))
}
