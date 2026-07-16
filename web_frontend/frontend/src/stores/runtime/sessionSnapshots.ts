import type { ContextWindowView, ConversationTurn, FactoryMode, RunStatus, RuntimePlanView, TranscriptItem } from '@/types/protocol'
import { conversationScopeForMode } from './scopes'

export interface FactorySessionSnapshotView {
  restoredMode: FactoryMode | null
  scope: string | null
  hasMessages: boolean
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
  activeTurn: ConversationTurn | null
}

export interface AgentPackageSessionSnapshotView {
  sessionPackageId: string | null
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
  activeTurn: ConversationTurn | null
  contextWindow: ContextWindowView | null
  currentPlan: RuntimePlanView | null
}

export function factorySessionSnapshotView(
  payload: Record<string, any> | undefined,
): FactorySessionSnapshotView {
  const session = payload?.session || payload || {}
  const snapshot = session.snapshot || payload?.snapshot || {}
  const restoredMode = (snapshot.mode || session.current_mode || null) as FactoryMode | null
  const scope = conversationScopeForMode(restoredMode, payload || {})
  const restoredPackageId = restoredMode === 'evolve_agent'
    ? String(session.evolve_agent_package_id || payload?.package_id || '').trim() || null
    : null
  const rawTurns = Array.isArray(snapshot.turns) ? snapshot.turns : []
  if (rawTurns.length > 0) {
    const restored = conversationFromTurns(rawTurns, {
      keyPrefix: `factory-restored-${session.session_id || 'session'}`,
      mode: restoredMode,
      packageId: restoredPackageId,
      agentSessionId: null,
      fallbackTimestamp: session.updated_at,
    })
    return {
      restoredMode,
      scope,
      hasMessages: restored.transcript.length > 0,
      transcript: restored.transcript,
      conversationTurns: restored.conversationTurns,
      activeTurn: restored.activeTurn,
    }
  }
  return {
    restoredMode,
    scope,
    hasMessages: false,
    transcript: [],
    conversationTurns: [],
    activeTurn: null,
  }
}

export function agentPackageSessionSnapshotView(
  session: any,
  packageId: string | null = null,
): AgentPackageSessionSnapshotView {
  const sessionPackageId = packageId || session?.package_id || null
  const rawTurns = Array.isArray(session?.turns) ? session.turns : []
  const restored = conversationFromTurns(rawTurns, {
    keyPrefix: `agent-restored-${session.session_id}`,
    mode: 'agent_package',
    packageId: sessionPackageId,
    agentSessionId: session.session_id,
    fallbackTimestamp: session.updated_at,
  })

  return {
    sessionPackageId,
    transcript: restored.transcript,
    conversationTurns: restored.conversationTurns,
    activeTurn: restored.activeTurn,
    contextWindow: contextWindowFromSession(session),
    currentPlan: planFromSession(session),
  }
}

interface TurnRestoreContext {
  keyPrefix: string
  mode: FactoryMode | null
  packageId: string | null
  agentSessionId: string | null
  fallbackTimestamp?: string | null
}

function conversationFromTurns(rawTurns: any[], context: TurnRestoreContext) {
  const transcript: TranscriptItem[] = []
  const conversationTurns: ConversationTurn[] = []
  rawTurns.forEach((turn: any, index: number) => {
    if (!turn || typeof turn !== 'object') return
    const turnIndex = String(turn.index ?? index + 1)
    const createdAt = String(turn.created_at || context.fallbackTimestamp || new Date().toISOString())
    const updatedAt = String(turn.updated_at || createdAt)
    const turnMessages = Array.isArray(turn.messages) ? turn.messages : []
    const toolActivities = Array.isArray(turn.tool_activities) ? turn.tool_activities : []
    if (turnMessages.length > 0) {
      restoreTurnMessages({
        transcript,
        conversationTurns,
        rawMessages: turnMessages,
        turn,
        turnIndex,
        context,
        createdAt,
        updatedAt,
        toolActivities,
      })
      return
    }
  })
  return {
    transcript,
    conversationTurns,
    activeTurn: activeTurnFrom(conversationTurns),
  }
}

function restoreTurnMessages(options: {
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
  rawMessages: any[]
  turn: any
  turnIndex: string
  context: TurnRestoreContext
  createdAt: string
  updatedAt: string
  toolActivities: any[]
}) {
  const status = normalizeTurnStatus(options.turn.status, 'completed')
  const metadata = {
    restored: true,
    mode: options.context.mode,
    package_id: options.context.packageId,
    agent_session_id: options.context.agentSessionId,
  }
  const conversationTurn: ConversationTurn = {
    id: `${options.context.keyPrefix}-turn-${options.turnIndex}`,
    requestId: stringOrNull(options.turn.request_id),
    status,
    userMessage: null,
    assistantMessages: [],
    tools: options.toolActivities,
    startedAt: options.createdAt,
    completedAt: isActiveTurnStatus(status) ? null : options.updatedAt,
    errorMessage: null,
    metadata,
  }
  for (const rawMessage of options.rawMessages) {
    const item = transcriptItemFromPartMessage(rawMessage, {
      fallbackId: `${options.context.keyPrefix}-${options.turnIndex}-${options.transcript.length}`,
      fallbackTimestamp: rawMessage?.timestamp || options.updatedAt,
      metadata,
    })
    if (!item) continue
    options.transcript.push(item)
    if (item.role === 'user' && !conversationTurn.userMessage) {
      conversationTurn.userMessage = item
    } else if (item.role === 'assistant') {
      conversationTurn.assistantMessages.push(item)
    }
  }
  options.conversationTurns.push(conversationTurn)
}

function transcriptItemFromPartMessage(
  rawMessage: any,
  options: {
    fallbackId: string
    fallbackTimestamp: string
    metadata: Record<string, any>
  },
): TranscriptItem | null {
  if (!rawMessage || typeof rawMessage !== 'object') return null
  const role = rawMessage.role === 'assistant' ? 'assistant' : rawMessage.role === 'system' ? 'system' : 'user'
  const parts = Array.isArray(rawMessage.parts) ? rawMessage.parts : []
  if (parts.length === 0) return null
  const timestamp = String(rawMessage.timestamp || options.fallbackTimestamp || new Date().toISOString())
  const content = parts
    .filter((part: any) => part?.type === 'text')
    .map((part: any) => String(part.text || ''))
    .join('')
  const reasoning = parts.find((part: any) => part?.type === 'reasoning')
  const attachments = parts
    .filter((part: any) => part?.type === 'attachment' && part.attachment)
    .map((part: any) => part.attachment)
  return {
    id: String(rawMessage.id || options.fallbackId),
    role,
    content,
    timestamp,
    status: rawMessage.status || 'completed',
    parts,
    attachments,
    reasoning: reasoning?.text
      ? {
          content: String(reasoning.text),
          active: reasoning.status === 'streaming',
          completedAt: reasoning.status === 'streaming' ? null : reasoning.updatedAt || timestamp,
        }
      : undefined,
    metadata: {
      ...options.metadata,
      ...(rawMessage.metadata && typeof rawMessage.metadata === 'object' ? rawMessage.metadata : {}),
    },
  }
}

function normalizeTurnStatus(value: any, fallback: RunStatus): RunStatus {
  if (
    value === 'running' ||
    value === 'waiting_for_workers' ||
    value === 'interrupted' ||
    value === 'completed' ||
    value === 'stopped' ||
    value === 'cancelled' ||
    value === 'failed'
  ) {
    return value
  }
  return fallback
}

function isActiveTurnStatus(status: RunStatus): boolean {
  return status === 'running' || status === 'interrupted'
}

function activeTurnFrom(turns: ConversationTurn[]): ConversationTurn | null {
  return turns.find((turn) => isActiveTurnStatus(turn.status) && Boolean(turn.requestId)) || null
}

function stringOrNull(value: any): string | null {
  const text = String(value || '').trim()
  return text || null
}

function contextWindowFromSession(session: any): ContextWindowView | null {
  const payload = session?.context_window
  if (!payload || typeof payload !== 'object') return null
  return {
    tokenCount: optionalNumber(payload.token_count),
    contextWindowTokens: optionalNumber(payload.context_window_tokens),
    compressionThresholdTokens: optionalNumber(payload.compression_threshold_tokens),
    tokenCountMethod: optionalString(payload.token_count_method),
    source: optionalString(payload.source),
    modelRole: optionalString(payload.model_role),
    nodeId: optionalString(payload.node_id),
    updatedAt: String(payload.updated_at || session.updated_at || new Date().toISOString()),
    payload,
  }
}

function planFromSession(session: any): RuntimePlanView | null {
  const payload = session?.current_plan
  if (!payload || typeof payload !== 'object' || payload.version !== 'plan_state.v0') return null
  return {
    version: payload.version,
    goal: String(payload.goal || ''),
    status: String(payload.status || 'active'),
    current_step_id: payload.current_step_id || null,
    steps: Array.isArray(payload.steps) ? payload.steps : [],
    source_node_id: payload.source_node_id || null,
    updatedAt: payload.updated_at || session.updated_at || undefined,
  }
}

function optionalNumber(value: any): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function optionalString(value: any): string | null {
  const text = String(value || '').trim()
  return text || null
}
