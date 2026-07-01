import type { FactoryFrontendEvent, RuntimeViewState, ToolActivity } from '@/types/protocol'
import {
  upsertToolActivityFromEvent,
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
  const toolCallId = event.payload?.tool_call_id
  state.pendingInterrupt = null
  if (state.runStatus === 'interrupted') {
    state.runStatus = 'running'
  }

  if (toolCallId) {
    const tool = state.tools.find((item) => item.toolCallId === toolCallId)
    if (tool) {
      tool.approvalState = approved ? 'approved' : 'rejected'
      upsertTurnTool(state, tool)
    }
    return
  }

  state.tools
    .filter((tool) => tool.status === 'approval' && tool.approvalState === 'pending')
    .forEach((tool) => {
      tool.approvalState = approved ? 'approved' : 'rejected'
      upsertTurnTool(state, tool)
    })
}
