import type {
  ChatMessagePart,
  ToolCallMessagePart,
  ToolExecutionMessagePart,
  ToolResultMessagePart,
} from '@/types/protocol'

export type ToolCategory =
  | 'read'
  | 'write'
  | 'search'
  | 'process'
  | 'knowledge'
  | 'scheduler'
  | 'agent'
  | 'extension'
  | 'generic'

export interface ToolPresentation {
  category: ToolCategory
  labelKey: string
  icon: ToolIconName
  summary: string
  summaryKey?: string
}

export type ToolIconName =
  | 'document' | 'edit' | 'search' | 'terminal' | 'folder' | 'calendar'
  | 'agent' | 'task' | 'extension' | 'catalog' | 'memory' | 'browser'
  | 'view' | 'pointer' | 'type' | 'select' | 'keyboard' | 'scroll'
  | 'timer' | 'extract' | 'camera' | 'download' | 'upload' | 'tabs' | 'close'
  | 'generic'

const TOOL_PRESENTATIONS: Record<string, Pick<ToolPresentation, 'category' | 'labelKey' | 'icon'>> = {
  read: { category: 'read', labelKey: 'tool.names.read', icon: 'document' },
  write: { category: 'write', labelKey: 'tool.names.write', icon: 'edit' },
  edit: { category: 'write', labelKey: 'tool.names.edit', icon: 'edit' },
  glob: { category: 'search', labelKey: 'tool.names.glob', icon: 'search' },
  grep: { category: 'search', labelKey: 'tool.names.grep', icon: 'search' },
  ls: { category: 'read', labelKey: 'tool.names.ls', icon: 'folder' },
  shell: { category: 'process', labelKey: 'tool.names.shell', icon: 'terminal' },
  shell_status: { category: 'process', labelKey: 'tool.names.shellStatus', icon: 'task' },
  shell_stop: { category: 'process', labelKey: 'tool.names.shellStop', icon: 'close' },
  capability: { category: 'extension', labelKey: 'tool.names.capability', icon: 'catalog' },
  delegate: { category: 'agent', labelKey: 'tool.names.delegate', icon: 'agent' },
  delegation_status: { category: 'agent', labelKey: 'tool.names.delegationStatus', icon: 'task' },
  memory: { category: 'knowledge', labelKey: 'tool.names.memory', icon: 'memory' },
  knowledge: { category: 'knowledge', labelKey: 'tool.names.knowledge', icon: 'folder' },
  scheduler: { category: 'scheduler', labelKey: 'tool.names.scheduler', icon: 'calendar' },
  skillhub: { category: 'extension', labelKey: 'tool.names.skillhub', icon: 'extension' },
  skill: { category: 'extension', labelKey: 'tool.names.skill', icon: 'extension' },
  tool_output: { category: 'read', labelKey: 'tool.names.toolOutput', icon: 'document' },
  browser_open: { category: 'process', labelKey: 'tool.names.browserOpen', icon: 'browser' },
  browser_snapshot: { category: 'read', labelKey: 'tool.names.browserSnapshot', icon: 'view' },
  browser_click: { category: 'process', labelKey: 'tool.names.browserClick', icon: 'pointer' },
  browser_type: { category: 'write', labelKey: 'tool.names.browserType', icon: 'type' },
  browser_select: { category: 'process', labelKey: 'tool.names.browserSelect', icon: 'select' },
  browser_press: { category: 'process', labelKey: 'tool.names.browserPress', icon: 'keyboard' },
  browser_scroll: { category: 'process', labelKey: 'tool.names.browserScroll', icon: 'scroll' },
  browser_wait: { category: 'process', labelKey: 'tool.names.browserWait', icon: 'timer' },
  browser_extract: { category: 'read', labelKey: 'tool.names.browserExtract', icon: 'extract' },
  browser_screenshot: { category: 'read', labelKey: 'tool.names.browserScreenshot', icon: 'camera' },
  browser_download: { category: 'write', labelKey: 'tool.names.browserDownload', icon: 'download' },
  browser_upload: { category: 'write', labelKey: 'tool.names.browserUpload', icon: 'upload' },
  browser_tabs: { category: 'read', labelKey: 'tool.names.browserTabs', icon: 'tabs' },
  browser_close: { category: 'process', labelKey: 'tool.names.browserClose', icon: 'close' },
}

export function conversationVisibleParts(parts: ChatMessagePart[]): ChatMessagePart[] {
  return mergeToolMessageParts(parts)
}

export function toolPresentation(
  toolName: string,
  argumentsValue: unknown,
): ToolPresentation {
  const normalizedName = normalizedToolName(toolName)
  const configured = TOOL_PRESENTATIONS[normalizedName] || {
    category: 'generic' as const,
    labelKey: '',
    icon: 'generic' as const,
  }
  const argumentPresentation = toolArgumentPresentation(normalizedName, argumentsValue)
  return {
    ...configured,
    ...argumentPresentation,
  }
}

function normalizedToolName(toolName: string): string {
  const value = String(toolName || 'tool').trim()
  if (!value.startsWith('tool://builtin/')) return value
  return value.slice('tool://builtin/'.length).split('/')[0] || value
}

export function mergeToolMessageParts(parts: ChatMessagePart[]): ChatMessagePart[] {
  const merged: ChatMessagePart[] = []
  let activeExecution: ToolExecutionMessagePart | null = null

  for (const part of parts) {
    if (part.type === 'tool_call') {
      activeExecution = executionFromCall(part)
      merged.push(activeExecution)
      continue
    }
    if (part.type === 'tool_result') {
      const target = matchingExecution(merged, part)
      if (target) {
        target.output = part.output
        target.error = part.error
        target.status = part.status
        target.updatedAt = part.updatedAt
        activeExecution = target
      } else {
        activeExecution = executionFromResult(part)
        merged.push(activeExecution)
      }
      continue
    }
    if (part.type === 'artifact' && activeExecution) {
      activeExecution.artifacts.push(part)
      continue
    }
    activeExecution = null
    merged.push(part)
  }
  return merged
}

function executionFromCall(part: ToolCallMessagePart): ToolExecutionMessagePart {
  return {
    id: `${part.id}:execution`,
    type: 'tool_execution',
    toolName: part.toolName,
    callId: part.callId,
    arguments: part.arguments,
    output: part.liveOutput ?? null,
    approvalState: part.approvalState,
    artifacts: [],
    status: part.status,
    createdAt: part.createdAt,
    startedAt: part.startedAt,
    updatedAt: part.updatedAt,
  }
}

function executionFromResult(part: ToolResultMessagePart): ToolExecutionMessagePart {
  return {
    id: `${part.id}:execution`,
    type: 'tool_execution',
    toolName: part.toolName,
    callId: part.callId,
    arguments: {},
    output: part.output,
    error: part.error,
    artifacts: [],
    status: part.status,
    createdAt: part.createdAt,
    startedAt: part.startedAt,
    updatedAt: part.updatedAt,
  }
}

function matchingExecution(
  parts: ChatMessagePart[],
  result: ToolResultMessagePart,
): ToolExecutionMessagePart | null {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const candidate = parts[index]
    if (candidate.type !== 'tool_execution') continue
    if (result.callId && candidate.callId === result.callId) return candidate
    if (!result.callId && candidate.toolName === result.toolName && candidate.output == null) return candidate
  }
  return null
}

function toolArgumentPresentation(
  toolName: string,
  value: unknown,
): Pick<ToolPresentation, 'summary' | 'summaryKey'> {
  const args = recordValue(value)
  if (!args) return { summary: '' }
  if (toolName === 'ls' && isWorkspaceRoot(args.path)) {
    return { summary: '', summaryKey: 'tool.location.workspaceRoot' }
  }
  if (toolName === 'shell') return summary(compact(args.command))
  if (toolName === 'grep') return summary(compact(args.pattern, args.base_path))
  if (toolName === 'glob') return summary(compact(args.pattern, args.base_path))
  if (toolName === 'edit') {
    const operations = Array.isArray(args.operations) ? args.operations : []
    const paths = operations
      .flatMap(operation => {
        const record = recordValue(operation)
        return record ? [record.path, record.source_path, record.destination_path] : []
      })
      .filter(Boolean)
      .slice(0, 2)
    return summary(compact(args.action, ...paths, args.transaction_id))
  }
  if (toolName === 'read' || toolName === 'write' || toolName === 'ls') {
    return summary(compact(args.path))
  }
  if (toolName === 'shell_status' || toolName === 'shell_stop') return summary(compact(args.process_id))
  if (toolName === 'knowledge') return summary(compact(args.action, args.query))
  if (toolName === 'scheduler') return summary(compact(args.action, args.job_id))
  if (toolName === 'skillhub') return summary(compact(args.action, args.query || args.slug))
  if (toolName === 'capability') return summary(compact(args.action, args.query))
  if (toolName === 'memory') return summary(compact(args.action, args.query || args.kind))
  if (toolName === 'delegate') return summary(compact(args.agent_name, args.objective))
  if (toolName === 'delegation_status') return { summary: '' }
  if (toolName.startsWith('browser_')) {
    return summary(compact(args.url, args.path, args.key, args.format, args.milliseconds))
  }
  if (toolName.startsWith('agent_')) return summary(compact(args.query, args.package_id || args.agent_id))
  return { summary: '' }
}

function summary(value: string): Pick<ToolPresentation, 'summary'> {
  return { summary: value }
}

function isWorkspaceRoot(value: unknown): boolean {
  const path = String(value ?? '').trim().replace(/\\/g, '/').replace(/\/+$/, '')
  return path === '.' || path === './' || path === '/workdir'
}

function recordValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
}

function compact(...values: unknown[]): string {
  const text = values
    .map(value => String(value || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(' · ')
  return text.length > 120 ? `${text.slice(0, 117)}...` : text
}
