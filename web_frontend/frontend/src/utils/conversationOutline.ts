import type { ConversationTimelineItem } from '@/composables/conversation/useConversationMessageProjection'
import type { ChatMessagePart } from '@/types/protocol'
import { conversationVisibleMessageParts } from '@/utils/toolPresentation'

export interface ConversationOutlineEntry {
  id: string
  anchorId: string
  anchorIds: string[]
  userMessage: string
  timestamp: string
}

export function buildConversationOutline(items: readonly ConversationTimelineItem[]): ConversationOutlineEntry[] {
  const entries: ConversationOutlineEntry[] = []
  let current: ConversationOutlineEntry | null = null

  for (const item of items) {
    if (item.message.role === 'user') {
      const parts = conversationVisibleMessageParts(item.messages)
      current = {
        id: item.id,
        anchorId: item.id,
        anchorIds: [item.id],
        userMessage: lastTextPart(parts),
        timestamp: item.timestamp,
      }
      entries.push(current)
    } else if (current) {
      current.anchorIds.push(item.id)
    }
  }

  return entries
}

function lastTextPart(parts: ChatMessagePart[]): string {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.type === 'text' && part.text.trim()) return part.text
  }
  return ''
}
