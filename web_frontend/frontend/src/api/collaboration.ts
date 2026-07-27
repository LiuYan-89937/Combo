import { requestJson } from './http'

export type CollaborationApprovalMode = 'user_controlled' | 'main_agent_delegated'
export type CollaborationSessionStatus = 'draft' | 'running' | 'completed' | 'failed' | 'cancelled'
export type CollaborationRuntimeStatus =
  | 'waiting_for_workers'
  | 'waiting_for_approval'
  | 'waiting_for_dependency'
  | 'resuming_from_event'
export type CollaborationTaskStatus =
  | 'assigned'
  | 'queued'
  | 'accepted'
  | 'planning'
  | 'working'
  | 'blocked'
  | 'submitted'
  | 'revision_requested'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface CollaborationAgentView {
  package_id: string
  agent_name: string
  agent_description?: string
  source?: string
  available_as_main: boolean
  available_as_worker: boolean
  status?: string | null
}

export interface CollaborationMessageView {
  message_id: string
  collaboration_id: string
  speaker_type: 'user' | 'main_agent' | 'worker_agent' | 'system' | string
  speaker_package_id?: string | null
  message_kind: string
  content: string
  task_id?: string | null
  event_ref?: string | null
  created_at: string
}

export interface CollaborationTaskView {
  task_id: string
  collaboration_id: string
  parent_task_id?: string | null
  assignee_package_id: string
  assignee_session_id?: string | null
  task_text: string
  depends_on: string[]
  delivery_standard: Record<string, any>
  visible_context: Record<string, any>
  input_artifacts: any[]
  status: CollaborationTaskStatus
  result_summary: string
  result_payload: Record<string, any>
  artifact_refs: any[]
  review_notes: string
  created_at: string
  updated_at: string
}

export interface CollaborationManufacturingRequestView {
  request_id: string
  collaboration_id: string
  agent_name: string
  purpose: string
  status: string
  create_agent_session_id?: string | null
  result_payload?: Record<string, any>
  message?: string | null
  created_at?: string
  updated_at?: string
}

export interface CollaborationSessionView {
  collaboration_id: string
  title: string
  main_agent_package_id: string
  main_agent_package_session_id?: string | null
  approval_mode: CollaborationApprovalMode
  execution_config?: {
    model_profile_id?: string | null
    reasoning_intensity?: number | null
  }
  round_index?: number
  started_at?: string | null
  completed_at?: string | null
  statistics?: CollaborationStatisticsView
  status: CollaborationSessionStatus
  runtime_status?: CollaborationRuntimeStatus | null
  runtime_status_payload?: Record<string, any>
  created_at: string
  updated_at: string
  acceptance_workspace?: {
    resource_mode: 'collaboration'
    collaboration_id: string
    workdir: string
  }
  messages?: CollaborationMessageView[]
  tasks?: CollaborationTaskView[]
  manufacturing_requests?: CollaborationManufacturingRequestView[]
}

export interface CollaborationStatisticsView {
  round_index: number
  wall_duration_ms: number | null
  cumulative_task_duration_ms: number
  task_count: number
  task_status_counts: Record<string, number>
  retry_count: number
  model_usage: {
    totals: {
      call_count: number
      input_tokens: number
      output_tokens: number
      total_tokens: number
      reasoning_tokens: number
      cache_hit_tokens: number
      cache_miss_tokens: number
      cache_hit_ratio: number | null
    }
    by_agent: Array<Record<string, any>>
    by_model: Array<Record<string, any>>
    by_task: Array<Record<string, any>>
  }
}

export const collaborationApi = {
  agents: () => requestJson<{ agents: CollaborationAgentView[] }>('/api/collaboration/agents'),
  sessions: () => requestJson<{ sessions: CollaborationSessionView[] }>('/api/collaboration/sessions'),
  createSession: (payload: {
    title: string
    main_agent_package_id: string
    approval_mode: CollaborationApprovalMode
  }) => requestJson<{ session: CollaborationSessionView }>('/api/collaboration/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  session: (collaborationId: string) =>
    requestJson<{ session: CollaborationSessionView }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}`),
  updateSession: (collaborationId: string, payload: Partial<Pick<CollaborationSessionView, 'title' | 'main_agent_package_id' | 'main_agent_package_session_id' | 'approval_mode' | 'execution_config' | 'status'>>) =>
    requestJson<{ session: CollaborationSessionView }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  completeSession: (collaborationId: string, payload: { final_summary: string }) =>
    requestJson<{ session: CollaborationSessionView }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/complete`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  deleteSession: (collaborationId: string) =>
    requestJson<{
      collaboration_id: string
      deleted: boolean
      main_agent_package_id?: string | null
      main_agent_package_session_id?: string | null
      sessions: CollaborationSessionView[]
    }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}`, {
      method: 'DELETE',
    }),
  addMessage: (collaborationId: string, payload: Partial<CollaborationMessageView>) =>
    requestJson<{ session: CollaborationSessionView }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  mainAgentPrompt: (collaborationId: string, message: string) =>
    requestJson<{
      prompt: string
      runtime_tool_access: {
        extra_allowed_tool_ids: string[]
        excluded_tool_ids: string[]
      }
    }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/main-agent-prompt`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
  createTask: (collaborationId: string, payload: {
    assignee_package_id: string
    task_text: string
    delivery_standard?: Record<string, any>
    visible_context?: Record<string, any>
    input_artifacts?: any[]
    depends_on?: string[]
  }) => requestJson<{ session: CollaborationSessionView }>(`/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  startTask: (collaborationId: string, taskId: string) =>
    requestJson<{ result: Record<string, any> | null; session: CollaborationSessionView; message?: string | null }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks/${encodeURIComponent(taskId)}/start`,
      { method: 'POST' },
    ),
  cancelTask: (collaborationId: string, taskId: string, payload: { review_notes?: string } = {}) =>
    requestJson<{ session: CollaborationSessionView }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks/${encodeURIComponent(taskId)}/cancel`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  retryTask: (collaborationId: string, taskId: string, payload: { retry_guidance?: string } = {}) =>
    requestJson<{ session: CollaborationSessionView; task: CollaborationTaskView; replaced_task_id: string }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks/${encodeURIComponent(taskId)}/retry`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  resolveTaskApproval: (collaborationId: string, taskId: string, payload: {
    action: 'approve' | 'deny' | 'revise'
    revision_guidance?: string
  }) =>
    requestJson<{ result: Record<string, any> | null; session: CollaborationSessionView; message?: string | null }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks/${encodeURIComponent(taskId)}/approval`,
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    ),
  dispatchReady: (collaborationId: string, limit?: number) =>
    requestJson<{ started_count: number; results: Record<string, any>[]; session: CollaborationSessionView }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/dispatch-ready`,
      {
        method: 'POST',
        body: JSON.stringify(limit ? { limit } : {}),
      },
    ),
  updateTask: (collaborationId: string, taskId: string, payload: Partial<CollaborationTaskView>) =>
    requestJson<{ session: CollaborationSessionView }>(
      `/api/collaboration/sessions/${encodeURIComponent(collaborationId)}/tasks/${encodeURIComponent(taskId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    ),
}
