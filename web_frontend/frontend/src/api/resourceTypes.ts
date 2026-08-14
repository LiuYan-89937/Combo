export type WorkspaceScope = 'package' | 'runtime' | 'workdir' | 'artifacts' | 'extensions'
export type WorkspaceResourceMode = 'package' | 'agent_group'

export interface WorkspaceRequestContext {
  resourceMode?: WorkspaceResourceMode
  packageId?: string | null
  packageSessionId?: string | null
  workspaceId?: string | null
  groupId?: string | null
}

export type WorkspaceContextInput = WorkspaceRequestContext | string | null | undefined

export interface KnowledgeSourceInput {
  kind: 'folder' | 'file' | 'url' | 'note'
  display_name: string
  uri: string
  content?: string
  mount_mode: 'index_only' | 'rag'
  files?: KnowledgeUploadFile[]
  chunking?: {
    chunk_size: number
    chunk_overlap: number
  }
}

export interface KnowledgeUploadFile {
  file: File
  relativePath: string
}

export interface McpServerConfig {
  server_id?: string
  display_name: string
  description?: string
  transport: 'stdio' | 'streamable_http' | 'sse'
  command?: string
  args?: string | string[]
  cwd?: string
  env?: string | Record<string, string | McpBindingReference>
  url?: string
  headers?: string | Record<string, string | McpBindingReference>
  timeout_seconds: number
  connect_timeout_seconds?: number
  max_parallel_requests?: number
  concurrent_default?: boolean
  enabled: boolean
  risk_level_default?: 'low' | 'medium' | 'high'
  source?: {
    type: 'local' | 'remote' | 'imported'
    name: string
    description?: string
  }
}

export type McpBindingReference =
  | { source: 'process_environment'; name: string }
  | { source: 'literal'; value: string }

export interface SkillConfig {
  path: string
  source: 'local' | string
  enabled: boolean
  required?: boolean
  replace_skill_id?: string
}

export type ScheduleType = 'cron' | 'interval' | 'date'
export type SchedulerTargetType = 'graph_run' | 'script_run'
export interface SchedulerJobInput {
  workspace_id: string
  task_content: string
  strategy: 'auto' | 'react' | 'plan_and_execute'
  approval_policy: 'ask' | 'auto' | 'always_approval'
  schedule_type: ScheduleType
  schedule_expr: string
  enabled?: boolean
  runtime_config?: {
    user_config?: Record<string, any>
    runtime_request?: Record<string, any>
  }
  target:
    | {
        target_type: 'graph_run'
        payload: {
          message: string
        }
      }
    | {
      target_type: 'script_run'
      payload: {
          interpreter: 'shell' | 'python'
          script: string
        }
      }
}

export interface SchedulerRunView {
  run_id: string
  job_id: string
  status: 'queued' | 'running' | 'waiting_approval' | 'waiting_external' | 'completed' | 'failed' | 'cancelled'
  executor_type: 'agent' | 'script'
  scheduled_at: string
  started_at?: string | null
  completed_at?: string | null
  task_content?: string
  result_summary?: string
  result?: Record<string, unknown>
  error?: Record<string, unknown>
  job_snapshot?: Record<string, any>
}

export interface SchedulerRunEventView {
  run_id: string
  sequence: number
  event_type: string
  payload: Record<string, any>
  created_at: string
}
