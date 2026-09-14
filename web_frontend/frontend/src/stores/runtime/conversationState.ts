import type { ConversationScopeState, RuntimeViewState } from '@/types/protocol'

export const CONVERSATION_STATE_KEYS = [
  'historyBefore',
  'transcript',
  'conversationTurns',
  'timeline',
  'tools',
  'currentPlan',
  'runtimeActivity',
  'computerUseActivity',
  'contextActivity',
  'contextWindow',
  'memoryActivity',
  'modelStreams',
  'activeMainSessionId',
  'activeAgentSessionId',
  'activeWorkspaceId',
  'activeRequestId',
  'runStatus',
  'pendingInterrupt',
  'currentRunId',
  'nodes',
  'stages',
] as const satisfies readonly (keyof ConversationScopeState)[]

type ConversationScopeSource = Pick<
  RuntimeViewState,
  (typeof CONVERSATION_STATE_KEYS)[number]
>

/**
 * Capture the field references owned by one conversation. Replacing a field is
 * captured before the next switch, while item mutations remain visible through
 * the shared reference. Switching therefore stays independent of history size.
 */
export function captureConversationScopeState(
  source: ConversationScopeSource,
): ConversationScopeState {
  return {
    historyBefore: source.historyBefore,
    transcript: source.transcript,
    conversationTurns: source.conversationTurns,
    timeline: source.timeline,
    tools: source.tools,
    currentPlan: source.currentPlan,
    runtimeActivity: source.runtimeActivity,
    computerUseActivity: source.computerUseActivity,
    contextActivity: source.contextActivity,
    contextWindow: source.contextWindow,
    memoryActivity: source.memoryActivity,
    modelStreams: source.modelStreams,
    activeMainSessionId: source.activeMainSessionId,
    activeAgentSessionId: source.activeAgentSessionId,
    activeWorkspaceId: source.activeWorkspaceId,
    activeRequestId: source.activeRequestId,
    runStatus: source.runStatus,
    pendingInterrupt: source.pendingInterrupt,
    currentRunId: source.currentRunId,
    nodes: source.nodes,
    stages: source.stages,
  }
}

export function createConversationScopeState(): ConversationScopeState {
  return {
    historyBefore: null,
    transcript: [],
    conversationTurns: [],
    timeline: [],
    tools: [],
    currentPlan: null,
    runtimeActivity: { status: 'idle' },
    computerUseActivity: { status: 'idle' },
    contextActivity: { status: 'idle' },
    contextWindow: null,
    memoryActivity: { status: 'idle' },
    modelStreams: {},
    activeMainSessionId: null,
    activeAgentSessionId: null,
    activeWorkspaceId: null,
    activeRequestId: null,
    runStatus: 'idle',
    pendingInterrupt: null,
    currentRunId: null,
    nodes: {},
    stages: {},
  }
}

export function isConversationStateKey(
  property: PropertyKey,
): property is (typeof CONVERSATION_STATE_KEYS)[number] {
  return typeof property === 'string'
    && (CONVERSATION_STATE_KEYS as readonly string[]).includes(property)
}
