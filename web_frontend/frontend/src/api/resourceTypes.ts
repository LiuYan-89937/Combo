export type WorkspaceScope = 'package' | 'runtime' | 'workdir' | 'artifacts' | 'extensions'
export type WorkspaceResourceMode = 'package' | 'create_agent' | 'evolve_agent'

export interface WorkspaceRequestContext {
  resourceMode?: WorkspaceResourceMode
  packageId?: string | null
  factorySessionId?: string | null
  createAgentSessionId?: string | null
}

export type WorkspaceContextInput = WorkspaceRequestContext | string | null | undefined

export interface KnowledgeSourceInput {
  kind: 'folder' | 'file' | 'url' | 'note'
  display_name: string
  uri: string
  content?: string
  mount_mode: 'index_only' | 'rag'
  files?: KnowledgeUploadFile[]
  ingestion_plan?: {
    planner: 'system_default'
    default_splitter: 'recursive' | 'markdown' | 'code' | 'json'
    default_chunk_size: number
    default_chunk_overlap: number
    rules: Array<{
      match: string
      splitter: 'recursive' | 'markdown' | 'code' | 'json'
      chunk_size: number
      chunk_overlap: number
      reason?: string
    }>
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
  transport: 'stdio'
  command: string
  args: string
  cwd: string
  env?: string | Record<string, string>
  timeout_seconds: number
  enabled: boolean
  source?: {
    type: 'local'
    name: string
    description?: string
  }
}

export interface SkillConfig {
  path: string
  source: 'local' | string
  enabled: boolean
  required?: boolean
  replace_skill_id?: string
}

export type ScheduleType = 'cron' | 'interval' | 'date'
export type SchedulerTargetType = 'graph_run' | 'script_run' | 'tool_call'
export type SchedulerThreadPolicy = 'new_thread_per_run' | 'fixed_thread'

export interface SchedulerJobInput {
  task_content: string
  schedule_type: ScheduleType
  schedule_expr: string
  enabled?: boolean
  target:
    | {
        target_type: 'graph_run'
        payload: {
          message: string
          thread_policy: SchedulerThreadPolicy
          fixed_thread_id?: string
        }
      }
    | {
        target_type: 'script_run'
        payload: {
          command: string
        }
      }
    | {
        target_type: 'tool_call'
        payload: {
          tool_id: string
          arguments?: Record<string, any>
        }
      }
}
