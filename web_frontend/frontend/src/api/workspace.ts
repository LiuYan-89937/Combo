import type { WorkspaceContextInput, WorkspaceRequestContext, WorkspaceScope } from './resourceTypes'
import { resolvedBackendUrl } from './backendUrl'
import { requestEvent, requestJson, withQuery } from './http'

export const workspaceApi = {
  roots: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/roots', workspaceQuery(context))),
  entries: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, ...workspaceQuery(context) })),
  file: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput, maxChars?: number) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context), max_chars: maxChars })),
  rawUrl: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    resolvedBackendUrl(withQuery('/api/workspace/raw', { scope, path, ...workspaceQuery(context) })),
  nativePath: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestJson<{ native_path: string; kind: 'file' | 'directory' }>(
      withQuery('/api/workspace/native-path', { scope, path, ...workspaceQuery(context) }),
    ),
  deleteFile: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestJson<{ deleted: boolean; path: string }>(
      withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context) }),
      { method: 'DELETE' },
    ),
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
