import type { ConversationTurn, FactoryMode, TranscriptItem } from '@/types/protocol'
import { conversationScopeForMode } from './scopes'

export interface FactorySessionSnapshotView {
  restoredMode: FactoryMode | null
  scope: string | null
  hasMessages: boolean
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
}

export interface AgentPackageSessionSnapshotView {
  sessionPackageId: string | null
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
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
      turnsByIndex.set(turnKey, {
        id: `restored-turn-${turnKey}`,
        requestId: null,
        status: 'completed',
        userMessage: null,
        assistantMessages: [],
        tools: [],
        startedAt: item.timestamp,
        completedAt: item.timestamp,
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
    turn.completedAt = item.timestamp
  })

  return {
    restoredMode,
    scope,
    hasMessages: messages.length > 0,
    transcript,
    conversationTurns: Array.from(turnsByIndex.values()),
  }
}

export function agentPackageSessionSnapshotView(
  session: any,
  packageId: string | null = null,
): AgentPackageSessionSnapshotView {
  const sessionPackageId = packageId || session?.package_id || null
  const transcript: TranscriptItem[] = []
  const turns: ConversationTurn[] = []
  const rawTurns = Array.isArray(session?.turns) ? session.turns : []

  rawTurns.forEach((turn: any, index: number) => {
    const turnIndex = String(turn?.index ?? index + 1)
    const timestamp = String(turn?.created_at || session.updated_at || new Date().toISOString())
    const metadata = {
      restored: true,
      mode: 'agent_package',
      package_id: sessionPackageId,
      agent_session_id: session.session_id,
    }
    const conversationTurn: ConversationTurn = {
      id: `agent-restored-turn-${session.session_id}-${turnIndex}`,
      requestId: null,
      status: 'completed',
      userMessage: null,
      assistantMessages: [],
      tools: [],
      startedAt: timestamp,
      completedAt: timestamp,
      errorMessage: null,
      metadata,
    }

    const userInput = String(turn?.user_input || '').trim()
    if (userInput) {
      const item: TranscriptItem = {
        id: `agent-restored-${session.session_id}-${turnIndex}-user`,
        role: 'user',
        content: userInput,
        timestamp,
        attachments: transcriptAttachmentViews(turn?.attachments),
        metadata,
      }
      transcript.push(item)
      conversationTurn.userMessage = item
    }

    const finalAnswer = String(turn?.final_answer || '').trim()
    if (finalAnswer) {
      const item: TranscriptItem = {
        id: `agent-restored-${session.session_id}-${turnIndex}-assistant`,
        role: 'assistant',
        content: finalAnswer,
        timestamp,
        reasoning: restoredReasoningView(turn),
        metadata,
      }
      transcript.push(item)
      conversationTurn.assistantMessages.push(item)
    }

    if (conversationTurn.userMessage || conversationTurn.assistantMessages.length > 0) {
      turns.push(conversationTurn)
    }
  })

  return {
    sessionPackageId,
    transcript,
    conversationTurns: turns,
  }
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
