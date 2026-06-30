/**
 * API 层 - 命令封装
 * 提供类型安全的命令发送接口
 */

import type { FactoryFrontendCommand, FactoryMode } from '@/types/protocol'

let requestIdCounter = 0

export function generateRequestId(): string {
  return `web-${Date.now()}-${++requestIdCounter}-${Math.random().toString(36).slice(2, 9)}`
}

export function createCommand(
  type: FactoryFrontendCommand['type'],
  options: Partial<Omit<FactoryFrontendCommand, 'type'>> = {}
): FactoryFrontendCommand {
  return {
    type,
    request_id: options.request_id || null,
    session_id: options.session_id || null,
    resume_latest: options.resume_latest || false,
    mode: options.mode || null,
    message: options.message || null,
    payload: options.payload || {},
    options: options.options || {},
  }
}

// ============= Session Commands =============

export function startSessionCommand(resumeLatest = false): FactoryFrontendCommand {
  return createCommand('start_session', { resume_latest: resumeLatest })
}

export function listSessionsCommand(): FactoryFrontendCommand {
  return createCommand('list_sessions')
}

export function switchSessionCommand(sessionId: string): FactoryFrontendCommand {
  return createCommand('switch_session', { session_id: sessionId })
}

export function newSessionCommand(): FactoryFrontendCommand {
  return createCommand('new_session')
}

export function setModeCommand(mode: FactoryMode): FactoryFrontendCommand {
  return createCommand('set_mode', { mode })
}

// ============= Message Commands =============

export interface SendMessageOptions {
  message: string
  mode?: FactoryMode
  attachments?: Array<{
    kind: 'file' | 'text' | 'url'
    name: string
    content?: string
    mime_type?: string
  }>
}

export function sendMessageCommand(options: SendMessageOptions): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('send_message', {
    request_id: requestId,
    mode: options.mode,
    message: options.message,
    payload: options.attachments ? { attachments: options.attachments } : {},
  })
}

// ============= Agent Package Commands =============

export function listAgentPackagesCommand(): FactoryFrontendCommand {
  return createCommand('list_agent_packages')
}

export function selectAgentPackageCommand(packageId: string, purpose?: 'run' | 'evolution'): FactoryFrontendCommand {
  return createCommand('select_agent_package', {
    payload: { package_id: packageId, purpose },
  })
}

export function deleteAgentPackageCommand(packageId: string): FactoryFrontendCommand {
  return createCommand('delete_agent_package', {
    payload: { package_id: packageId },
  })
}

export function listAgentPackageSessionsCommand(packageId: string): FactoryFrontendCommand {
  return createCommand('list_agent_package_sessions', {
    payload: { package_id: packageId },
  })
}

export function runAgentPackageCommand(
  packageId: string,
  message: string,
  sessionId?: string
): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_package', {
    request_id: requestId,
    payload: {
      package_id: packageId,
      message,
      session_id: sessionId,
    },
  })
}

export function runAgentEvolutionCommand(packageId: string, message: string): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('run_agent_evolution', {
    request_id: requestId,
    payload: { package_id: packageId },
    message,
  })
}

// ============= Interrupt Commands =============

export interface ResumeInterruptOptions {
  action: 'approve' | 'deny' | 'trust_tool' | 'revise'
  approved: boolean
  trust_scope?: 'tool' | 'tool_group'
  revision_guidance?: string
}

export function resumeInterruptCommand(options: ResumeInterruptOptions): FactoryFrontendCommand {
  const requestId = generateRequestId()
  return createCommand('resume_interrupt', {
    request_id: requestId,
    payload: options,
  })
}

export function cancelRuntimeRequestCommand(reason = 'user_cancelled'): FactoryFrontendCommand {
  return createCommand('cancel_runtime_request', {
    payload: { reason },
  })
}

// ============= Workspace Commands =============

export type WorkspaceScope = 'runtime' | 'workdir' | 'artifacts' | 'extensions'

export function workspaceRootsCommand(packageId?: string): FactoryFrontendCommand {
  return createCommand('workspace_manage', {
    payload: {
      action: 'roots',
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function listWorkspaceEntriesCommand(
  scope: WorkspaceScope,
  path: string,
  packageId?: string
): FactoryFrontendCommand {
  return createCommand('workspace_manage', {
    payload: {
      action: 'list',
      scope,
      path,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function readWorkspaceFileCommand(
  scope: WorkspaceScope,
  path: string,
  packageId?: string,
  maxChars = 120000
): FactoryFrontendCommand {
  return createCommand('workspace_manage', {
    payload: {
      action: 'read',
      scope,
      path,
      max_chars: maxChars,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

// ============= Knowledge Commands =============

export interface KnowledgeSourceInput {
  kind: 'folder' | 'file' | 'url' | 'note'
  display_name: string
  uri: string
  content?: string
  mount_mode: 'index_only' | 'rag'
}

export function listKnowledgeSourcesCommand(packageId?: string): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'list_sources',
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function prepareKnowledgeSourceCommand(
  source: KnowledgeSourceInput,
  packageId?: string
): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'prepare_source',
      source,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function confirmKnowledgeSourceCommand(
  source: KnowledgeSourceInput,
  packageId?: string
): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'confirm_source',
      source,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function listKnowledgeDocumentsCommand(sourceId: string, packageId?: string): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'list_documents',
      source_id: sourceId,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function searchKnowledgeCommand(query: string, sourceId?: string, packageId?: string): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'search',
      query,
      ...(sourceId ? { source_id: sourceId } : {}),
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function readKnowledgeDocumentCommand(
  documentId: string,
  packageId?: string
): FactoryFrontendCommand {
  return createCommand('knowledge_manage', {
    payload: {
      action: 'read',
      document_id: documentId,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

// ============= Extensions Commands =============

export function listExtensionsCommand(packageId?: string): FactoryFrontendCommand {
  return createCommand('extensions_manage', {
    payload: {
      action: 'list',
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export interface McpServerConfig {
  server_id?: string
  display_name: string
  transport: 'stdio'
  command: string
  args: string
  cwd: string
  env: string
  timeout_seconds: number
  enabled: boolean
  source?: {
    type: 'local'
    name: string
  }
}

export function upsertMcpCommand(server: McpServerConfig, packageId?: string): FactoryFrontendCommand {
  return createCommand('extensions_manage', {
    payload: {
      action: 'upsert_mcp',
      server,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function testMcpCommand(
  serverIdOrConfig: string | McpServerConfig,
  packageId?: string
): FactoryFrontendCommand {
  const payload: any = {
    action: 'test_mcp',
    ...(packageId ? { package_id: packageId } : {}),
  }

  if (typeof serverIdOrConfig === 'string') {
    payload.server_id = serverIdOrConfig
  } else {
    payload.server = serverIdOrConfig
  }

  return createCommand('extensions_manage', { payload })
}

export function setMcpEnabledCommand(
  serverId: string,
  enabled: boolean,
  packageId?: string
): FactoryFrontendCommand {
  return createCommand('extensions_manage', {
    payload: {
      action: 'set_mcp_enabled',
      server_id: serverId,
      enabled,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

export function removeMcpCommand(serverId: string, packageId?: string): FactoryFrontendCommand {
  return createCommand('extensions_manage', {
    payload: {
      action: 'remove_mcp',
      server_id: serverId,
      ...(packageId ? { package_id: packageId } : {}),
    },
  })
}

// ============= Scheduler Commands =============

export type ScheduleType = 'cron' | 'interval' | 'date'

export interface SchedulerJobInput {
  task_content: string
  schedule_type: ScheduleType
  schedule_expr: string
  target: {
    target_type: 'graph_run'
    payload: {
      message: string
      mode: FactoryMode
      thread_policy: 'new_thread_per_run' | 'resume_thread'
    }
  }
}

export function listSchedulerJobsCommand(): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'list' },
  })
}

export function createSchedulerJobCommand(job: SchedulerJobInput): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'create', job },
  })
}

export function describeSchedulerJobCommand(jobId: string): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'describe', job_id: jobId },
  })
}

export function listSchedulerRunsCommand(jobId?: string, limit = 20): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: {
      action: 'runs',
      ...(jobId ? { job_id: jobId } : {}),
      limit,
    },
  })
}

export function pauseSchedulerJobCommand(jobId: string): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'pause', job_id: jobId },
  })
}

export function resumeSchedulerJobCommand(jobId: string): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'resume', job_id: jobId },
  })
}

export function deleteSchedulerJobCommand(jobId: string): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'delete', job_id: jobId },
  })
}

export function runSchedulerJobNowCommand(jobId: string): FactoryFrontendCommand {
  return createCommand('scheduler_manage', {
    payload: { action: 'run_now', job_id: jobId },
  })
}

// ============= System Commands =============

export function setOptionsCommand(options: { show_state?: boolean; show_messages?: boolean }): FactoryFrontendCommand {
  return createCommand('set_options', { options })
}

export function shutdownCommand(): FactoryFrontendCommand {
  return createCommand('shutdown')
}
