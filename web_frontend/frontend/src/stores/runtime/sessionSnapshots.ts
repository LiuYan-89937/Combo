import type { ConversationTurn, FactoryMode, RunStatus, TranscriptItem } from '@/types/protocol'
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
  const messages = Array.isArray(snapshot.messages)
    ? snapshot.messages
    : Array.isArray(snapshot.transcript)
      ? snapshot.transcript
      : []

  const transcript: TranscriptItem[] = []
  const turnsByIndex = new Map<string, ConversationTurn>()

  messages.forEach((message: any, index: number) => {
    const role = message.role === 'assistant' ? 'assistant' : message.role === 'system' ? 'system' : 'user'
    const turnKey = String(message.turn_index ?? Math.floor(index / 2) + 1)
    const item: TranscriptItem = {
      id: `restored-${turnKey}-${role}-${index}`,
      role,
      content: String(message.content || ''),
      timestamp: String(message.created_at || message.timestamp || session.updated_at || new Date().toISOString()),
      attachments: role === 'user' ? transcriptAttachmentViews(message.attachments) : [],
      reasoning: restoredReasoningView(message),
      metadata: {
        restored: true,
        mode: restoredMode,
        package_id: restoredPackageId,
      },
    }
    if (!item.content.trim()) return
    transcript.push(item)
    if (!turnsByIndex.has(turnKey)) {
      const status = normalizeTurnStatus(message.status, 'completed')
      turnsByIndex.set(turnKey, {
        id: `restored-turn-${turnKey}`,
        requestId: stringOrNull(message.request_id),
        status,
        userMessage: null,
        assistantMessages: [],
        tools: [],
        startedAt: item.timestamp,
        completedAt: isActiveTurnStatus(status) ? null : item.timestamp,
        errorMessage: null,
        metadata: {
          restored: true,
          mode: restoredMode,
          package_id: restoredPackageId,
        },
      })
    }
    const turn = turnsByIndex.get(turnKey)!
    if (role === 'user' && !turn.userMessage) {
      turn.userMessage = item
    } else if (role === 'assistant') {
      turn.assistantMessages.push(item)
    }
    if (!isActiveTurnStatus(turn.status)) {
      turn.completedAt = item.timestamp
    }
  })
  const conversationTurns = Array.from(turnsByIndex.values())

  return {
    restoredMode,
    scope,
    hasMessages: messages.length > 0,
    transcript,
    conversationTurns,
    activeTurn: activeTurnFrom(conversationTurns),
  }
}

export function agentPackageSessionSnapshotView(
  session: any,
  packageId: string | null = null,
): AgentPackageSessionSnapshotView {
  const sessionPackageId = packageId || session?.package_id || null
  const rawTurns = Array.isArray(session?.turns) ? session.turns : []
  const restoredTurns = rawTurns.length > 0
    ? rawTurns
    : session?.first_user_input
      ? [{ index: 1, created_at: session.created_at || session.updated_at, user_input: session.first_user_input }]
      : []
  const restored = conversationFromTurns(restoredTurns, {
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
    const finalAnswer = String(turn.final_answer || '').trim()
    const userInput = String(turn.user_input || '').trim()
    if (!userInput && !finalAnswer) return
    const status = normalizeTurnStatus(turn.status, finalAnswer ? 'completed' : 'running')
    const metadata = {
      restored: true,
      mode: context.mode,
      package_id: context.packageId,
      agent_session_id: context.agentSessionId,
    }
    const conversationTurn: ConversationTurn = {
      id: `${context.keyPrefix}-turn-${turnIndex}`,
      requestId: stringOrNull(turn.request_id),
      status,
      userMessage: null,
      assistantMessages: [],
      tools: [],
      startedAt: createdAt,
      completedAt: isActiveTurnStatus(status) ? null : updatedAt,
      errorMessage: null,
      metadata,
    }

    if (userInput) {
      const item: TranscriptItem = {
        id: `${context.keyPrefix}-${turnIndex}-user`,
        role: 'user',
        content: userInput,
        timestamp: createdAt,
        attachments: transcriptAttachmentViews(turn.attachments),
        metadata,
      }
      transcript.push(item)
      conversationTurn.userMessage = item
    }

    if (finalAnswer) {
      const item: TranscriptItem = {
        id: `${context.keyPrefix}-${turnIndex}-assistant`,
        role: 'assistant',
        content: finalAnswer,
        timestamp: updatedAt,
        reasoning: restoredReasoningView(turn),
        metadata,
      }
      transcript.push(item)
      conversationTurn.assistantMessages.push(item)
    }

    conversationTurns.push(conversationTurn)
  })
  return {
    transcript,
    conversationTurns,
    activeTurn: activeTurnFrom(conversationTurns),
  }
}

function normalizeTurnStatus(value: any, fallback: RunStatus): RunStatus {
  if (
    value === 'running' ||
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

function restoredReasoningView(value: any) {
  const content = String(value?.reasoning_content || value?.reasoningContent || '').trim()
  if (!content) return undefined
  return {
    content,
    active: false,
    completedAt: value?.updated_at || value?.created_at || value?.timestamp || null,
  }
}

function transcriptAttachmentViews(value: any): TranscriptItem['attachments'] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item) => item && typeof item === 'object')
    .map((item) => {
      const kind: 'file' | 'text' | 'url' = item.kind === 'url' ? 'url' : item.kind === 'text' ? 'text' : 'file'
      return {
        kind,
        name: String(item.name || item.display_name || item.attachment_id || '').trim(),
        source_kind: item.source_kind ? String(item.source_kind) : undefined,
        mime_type: item.mime_type ? String(item.mime_type) : undefined,
      }
    })
    .filter((item) => item.name.length > 0)
}
