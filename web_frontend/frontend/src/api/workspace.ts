import type { WorkspaceContextInput, WorkspaceRequestContext, WorkspaceScope } from './resourceTypes'
import { resolvedBackendUrl } from './backendUrl'
import { requestEvent, requestJson, withQuery } from './http'

export const workspaceApi = {
  projects: () =>
    requestJson<{ workspaces: WorkspaceProjectView[] }>('/api/workspace/projects'),
  createProject: (payload: {
    title?: string | null
    mode?: WorkspaceProjectMode
    owner_package_id?: string | null
  }) =>
    requestJson<{ workspace: WorkspaceProjectView }>('/api/workspace/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProject: (
    workspaceId: string,
    payload: { title?: string; mode?: WorkspaceProjectMode; archived?: boolean },
  ) =>
    requestJson<{ workspace: WorkspaceProjectView }>(
      `/api/workspace/projects/${encodeURIComponent(workspaceId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    ),
  roots: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/roots', workspaceQuery(context))),
  entries: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, ...workspaceQuery(context) })),
  file: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput, maxChars?: number) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context), max_chars: maxChars })),
  rawUrl: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    resolvedBackendUrl(withQuery('/api/workspace/raw', { scope, path, ...workspaceQuery(context) })),
  deleteFile: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestJson<{ deleted: boolean; path: string }>(
      withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context) }),
      { method: 'DELETE' },
    ),
}

export type WorkspaceProjectMode = 'isolated' | 'project'

export interface WorkspaceProjectView {
  workspace_id: string
  title: string
  mode: WorkspaceProjectMode
  owner_package_id: string | null
  workdir_root: string
  archived: boolean
  created_at: string
  updated_at: string
}


function workspaceQuery(context: WorkspaceContextInput): Record<string, string | undefined | null> {
  if (typeof context === 'string') {
    return { package_id: context }
  }
  const normalized = normalizeWorkspaceContext(context)
  return {
    resource_mode: normalized.resourceMode,
    package_id: normalized.packageId,
    package_session_id: normalized.packageSessionId,
    factory_session_id: normalized.factorySessionId,
    create_agent_session_id: normalized.createAgentSessionId,
    collaboration_id: normalized.collaborationId,
    group_id: normalized.groupId,
  }
}

function normalizeWorkspaceContext(context: WorkspaceContextInput): WorkspaceRequestContext {
  return context && typeof context === 'object' ? context : {}
}
