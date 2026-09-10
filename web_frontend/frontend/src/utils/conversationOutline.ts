import type { ConversationTimelineItem } from '@/composables/conversation/useConversationMessageProjection'
import type { ChatMessagePart } from '@/types/protocol'
import { conversationVisibleMessageParts } from '@/utils/toolPresentation'
import { isToolExecutionFailed, isToolExecutionRunning } from '@/utils/toolTraceSummary'

export type ConversationOutlineStatus = 'running' | 'failed' | 'done'

export interface ConversationOutlineEntry {
  /** Stable key for the outline list. */
  id: string
  /** Timeline item id used by the transcript DOM anchor. */
  anchorId: string
  userPreview: string
  resultPreview: string
  timestamp: string
  toolCount: number
  status: ConversationOutlineStatus
}

/**
 * Collapses the transcript into one entry per user turn. Reading a long-running
 * task backwards is normally "which instruction was this?" plus "what came out
 * of it?", so each entry carries the user request and the closing answer. The
 * previews are derived from the same visible parts the transcript renders, so
 * the outline never disagrees with the message list.
 */
export function buildConversationOutline(
  items: readonly ConversationTimelineItem[],
  isStreaming: (item: ConversationTimelineItem) => boolean,
): ConversationOutlineEntry[] {
  const entries: ConversationOutlineEntry[] = []
  let current: ConversationOutlineEntry | null = null

  items.forEach((item) => {
    // The projection always populates `messages`, but the message itself is the
    // single source of truth when a caller hands over a bare timeline item.
    const sequence = item.messages.length ? item.messages : [item.message]
    const parts = conversationVisibleMessageParts(sequence)
    if (item.message.role === 'user') {
      current = {
        id: item.id,
        anchorId: item.id,
        userPreview: previewOf(lastTextPart(parts), 64),
        resultPreview: '',
        timestamp: item.timestamp,
        toolCount: 0,
        status: 'done',
      }
      entries.push(current)
      return
    }
    if (item.message.role !== 'assistant') return
    if (!current) {
      current = {
        id: item.id,
        anchorId: item.id,
        userPreview: '',
        resultPreview: '',
        timestamp: item.timestamp,
        toolCount: 0,
        status: 'done',
      }
      entries.push(current)
    }

    const resultText = lastTextPart(parts)
    if (resultText) current.resultPreview = markdownPreview(resultText, 88)

    const executions = parts.filter(part => part.type === 'tool_execution')
    current.toolCount += executions.length
    if (executions.some(isToolExecutionFailed)) {
      current.status = 'failed'
    } else if (current.status !== 'failed') {
      current.status = isStreaming(item) || executions.some(isToolExecutionRunning)
        ? 'running'
        : 'done'
    }
  })

  return entries
}

/** Turns markdown into a single flat line suitable for a narrow outline row. */
export function markdownPreview(value: string, limit: number): string {
  const text = String(value || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/~~~[\s\S]*?~~~/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s{0,3}[-*+]\s+/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/[*_~]{1,3}/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return previewOf(text, limit)
}

function previewOf(value: string, limit: number): string {
  const text = String(value || '').trim()
  if (text.length <= limit) return text
  return `${text.slice(0, limit).trimEnd()}…`
}

function lastTextPart(parts: ChatMessagePart[]): string {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.type === 'text' && part.text.trim()) return part.text
  }
  return ''
}
