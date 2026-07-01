import type {
  ContextWindowView,
  ExtensionItemView,
  FactoryFrontendEvent,
  KnowledgeDocumentView,
  KnowledgeSearchResultView,
  KnowledgeSourceView,
  SchedulerJobView,
  SchedulerRunNoticeView,
  SchedulerToolOptionView,
  WorkspaceEntry,
  WorkspaceFileView,
  WorkspaceRootView,
} from '@/types/protocol'

export function contextWindowView(event: FactoryFrontendEvent): ContextWindowView {
  const payload = event.payload || {}
  return {
    tokenCount: optionalNumber(payload.token_count),
    contextWindowTokens: optionalNumber(payload.context_window_tokens),
    compressionThresholdTokens: optionalNumber(payload.compression_threshold_tokens),
    tokenCountMethod: optionalString(payload.token_count_method),
    source: optionalString(payload.source),
    modelRole: optionalString(payload.model_role),
    nodeId: optionalString(payload.node_id || event.node_id),
    updatedAt: event.timestamp,
    payload,
  }
}

export function workspaceRootView(root: any): WorkspaceRootView {
  return {
    scope: root.scope,
    name: String(root.name || root.scope || 'Workspace'),
    exists: root.exists !== false,
  }
}

export function workspaceEntryView(entry: any): WorkspaceEntry {
  return {
    name: String(entry.name || entry.path || '文件'),
    scope: entry.scope,
    path: String(entry.path || ''),
    kind: entry.kind === 'directory' ? 'directory' : 'file',
    sizeBytes: entry.size_bytes ?? entry.sizeBytes ?? null,
    updatedAt: entry.updated_at || entry.updatedAt || null,
  }
}

export function workspaceFileView(payload: Record<string, any>): WorkspaceFileView {
  return {
    name: String(payload.name || payload.path || '文件'),
    scope: payload.scope,
    path: String(payload.path || ''),
    kind: payload.kind === 'binary' ? 'binary' : 'text',
    sizeBytes: Number(payload.size_bytes || payload.sizeBytes || 0),
    content: String(payload.content || ''),
    truncated: Boolean(payload.truncated),
    payload,
  }
}

export function knowledgeSourceView(source: any, timestamp: string): KnowledgeSourceView {
  const name = String(source?.display_name || source?.name || '知识源')
  return {
    name,
    status: String(source?.status || '更新中'),
    mode: source?.mount_mode || source?.mode || null,
    documentCount: source?.document_count ?? source?.estimated_documents ?? source?.counts?.documents_loaded ?? null,
    updatedAt: source?.updated_at || timestamp,
    payload: source || {},
  }
}

export function knowledgeDocumentView(document: any): KnowledgeDocumentView {
  return {
    documentId: document.document_id || document.documentId || undefined,
    title: String(document.title || document.uri || '文档'),
    sourceName: document.source_name || null,
    documentType: document.document_type || null,
    uri: document.uri || null,
    payload: document || {},
  }
}

export function knowledgeSearchResultView(result: any): KnowledgeSearchResultView {
  return {
    title: String(result.title || '搜索结果'),
    content: String(result.content || ''),
    score: typeof result.score === 'number' ? result.score : null,
    payload: result || {},
  }
}

export function schedulerJobView(job: any): SchedulerJobView {
  const target = job.target || {}
  const targetPayload = target.payload || {}
  const targetType = target.target_type || null
  return {
    title: String(job.task_content || job.title || '定时任务'),
    schedule: String(job.schedule_expr || '未设置'),
    enabled: job.enabled !== false,
    status: job.enabled === false ? '已暂停' : '已启用',
    targetType,
    targetLabel: schedulerJobTargetLabel(targetType, targetPayload),
    payload: job || {},
  }
}

export function schedulerToolOptionView(tool: any): SchedulerToolOptionView | null {
  const id = String(tool.id || '')
  if (!id) return null
  return {
    id,
    name: String(tool.name || tool.id || '工具'),
    description: tool.description ? String(tool.description) : undefined,
    riskLevel: tool.risk_level ? String(tool.risk_level) : undefined,
    inputSchema: tool.input_schema && typeof tool.input_schema === 'object' ? tool.input_schema : undefined,
  }
}

export function schedulerRunNoticeView(event: FactoryFrontendEvent): SchedulerRunNoticeView | null {
  const payload = event.payload || {}
  const nested = payload.payload && typeof payload.payload === 'object' ? payload.payload : {}
  const execution = nested.execution && typeof nested.execution === 'object' ? nested.execution : {}
  const runId = String(payload.run_id || execution.run_id || nested.run_id || '')
  const jobId = payload.job_id ? String(payload.job_id) : null
  const requestId = String(nested.request_id || execution.request_id || event.request_id || (runId ? `scheduler-${runId}` : ''))
  const status = String(payload.status || execution.status || '').trim() || event.event_type.replace('scheduler_run_', '')
  const targetType = payload.target_type ? String(payload.target_type) : null
  const targetScope = execution.target_scope ? String(execution.target_scope) : null
  const conversation = execution.conversation && typeof execution.conversation === 'object' ? execution.conversation : {}
  const agentSession = execution.agent_session && typeof execution.agent_session === 'object' ? execution.agent_session : {}
  const sessionId = String(conversation.session_id || agentSession.session_id || '').trim() || null
  const factorySessionId = conversation.mode === 'chat' && conversation.session_id ? String(conversation.session_id) : null
  const packageId = String(payload.package_id || execution.package_id || '').trim() || null
  const packageName = String(payload.package_name || execution.package_name || '').trim() || null
  const title = schedulerNoticeTitle(packageName, targetScope, targetType, packageId)
  const summary = String(
    payload.summary ||
    execution.output_summary ||
    execution.error_summary ||
    execution.error ||
    payload.error_summary ||
    schedulerStatusText(status)
  )
  if (!runId && !requestId) return null
  return {
    id: runId || requestId,
    jobId,
    runId: runId || null,
    requestId: requestId || null,
    status,
    title,
    summary,
    targetType,
    targetScope,
    packageId,
    packageName,
    sessionId,
    factorySessionId,
    reportPath: payload.report_path ? String(payload.report_path) : null,
    timestamp: event.timestamp,
    unread: !['scheduled', 'running', 'pending'].includes(status),
    payload,
  }
}

export function extensionItemView(item: any, fallbackKind: 'mcp' | 'skill'): ExtensionItemView {
  const kind = item.kind === 'skill' ? 'skill' : item.kind === 'mcp' ? 'mcp' : fallbackKind
  return {
    name: String(item.name || (kind === 'mcp' ? 'MCP' : 'Skill')),
    kind,
    scope: String(item.scope || 'local'),
    status: String(item.status || (item.enabled === false ? 'disabled' : 'enabled')),
    enabled: item.enabled !== false,
    payload: item.payload || item || {},
  }
}

function schedulerJobTargetLabel(targetType: string | null, payload: Record<string, any>): string {
  if (targetType === 'script_run') return '脚本'
  if (targetType === 'tool_call') return `工具：${payload.tool_id || '未选择'}`
  if (targetType === 'graph_run') return '自然语言任务'
  return targetType || '定时任务'
}

function schedulerNoticeTitle(
  packageName: string | null,
  targetScope: string | null,
  targetType: string | null,
  packageId: string | null,
): string {
  if (targetType === 'script_run') return '脚本定时任务'
  if (targetType === 'tool_call') return '工具定时任务'
  if (targetScope === 'agent_package' || packageId) return packageName ? `${packageName} 定时任务` : 'Agent 定时任务'
  return '闲聊定时任务'
}

function schedulerStatusText(status: string): string {
  const labels: Record<string, string> = {
    scheduled: '已调度',
    running: '运行中',
    completed: '已完成',
    failed: '运行失败',
    skipped: '已跳过',
    cancelled: '已取消',
  }
  return labels[status] || status || '状态更新'
}

function optionalNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function optionalString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}
