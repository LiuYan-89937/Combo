import type {
  AttachmentMessagePart,
  ChatMessagePart,
  TextMessagePart,
  ToolExecutionMessagePart,
} from '@/types/protocol'
import { isImageResource } from '@/utils/workspaceResources'

export type MessageDisplayBlock =
  | { kind: 'parts'; id: string; parts: ChatMessagePart[] }
  | { kind: 'images'; id: string; parts: AttachmentMessagePart[] }
  | { kind: 'tools'; id: string; executions: ToolExecutionMessagePart[]; timestamp: string }

export interface TurnDisplaySection {
  id: 'work' | 'delivery'
  isWork: boolean
  blocks: MessageDisplayBlock[]
}

const WORK_ONLY_PART_TYPES = new Set(['text', 'reasoning', 'tool_call', 'tool_result', 'tool_execution', 'status'])

/** The last text part is the answer only while no later tool execution exists. */
export function finalAnswerPart(parts: readonly ChatMessagePart[]): TextMessagePart | null {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const part = parts[index]
    if (part.type === 'tool_execution') return null
    if (part.type === 'text') return part
  }
  return null
}

export function buildTurnDisplaySections(
  parts: ChatMessagePart[],
  options: { answerPartId: string; showWork: boolean; workCollapsed: boolean; timestamp: string },
): TurnDisplaySection[] {
  if (!options.showWork) {
    return [{ id: 'delivery', isWork: false, blocks: buildDisplayBlocks(parts, options.timestamp) }]
  }

  const work: ChatMessagePart[] = []
  const delivery: ChatMessagePart[] = []
  for (const part of parts) {
    const isWork = part.id !== options.answerPartId && WORK_ONLY_PART_TYPES.has(part.type)
    if (isWork) work.push(part)
    else delivery.push(part)
  }
  return [
    ...(!options.workCollapsed
      ? [{ id: 'work' as const, isWork: true, blocks: buildDisplayBlocks(work, options.timestamp) }]
      : []),
    { id: 'delivery', isWork: false, blocks: buildDisplayBlocks(delivery, options.timestamp) },
  ]
}

function buildDisplayBlocks(parts: ChatMessagePart[], timestamp: string): MessageDisplayBlock[] {
  const blocks: MessageDisplayBlock[] = []
  let currentKind: 'parts' | 'images' | 'tools' | null = null
  let currentParts: ChatMessagePart[] = []
  const flush = () => {
    if (!currentKind || currentParts.length === 0) return
    if (currentKind === 'parts') {
      blocks.push({ kind: 'parts', id: `parts-${currentParts[0].id}`, parts: currentParts })
    } else if (currentKind === 'images') {
      const images = currentParts.filter(
        (part): part is AttachmentMessagePart => part.type === 'attachment',
      )
      if (images.length > 0) blocks.push({ kind: 'images', id: `images-${images[0].id}`, parts: images })
    } else {
      const executions = currentParts.filter(
        (part): part is ToolExecutionMessagePart => part.type === 'tool_execution',
      )
      blocks.push({
        kind: 'tools',
        id: `tools-${executions[0].id}`,
        executions,
        timestamp: executions[0].createdAt || timestamp,
      })
    }
    currentParts = []
  }
  for (const part of parts) {
    const nextKind = part.type === 'tool_execution'
      ? 'tools'
      : part.type === 'attachment' && isImageResource(part.attachment.name, part.attachment.mime_type)
        ? 'images'
        : 'parts'
    if (currentKind && currentKind !== nextKind) flush()
    currentKind = nextKind
    currentParts.push(part)
  }
  flush()
  return blocks
}
