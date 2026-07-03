import type { WorkspaceContextInput, WorkspaceRequestContext, WorkspaceScope } from './resourceTypes'
import { requestEvent, withQuery } from './http'

export const workspaceApi = {
  roots: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/roots', workspaceQuery(context))),
  entries: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, ...workspaceQuery(context) })),
  file: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput, maxChars?: number) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context), max_chars: maxChars })),
  rawUrl: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    withQuery('/api/workspace/raw', { scope, path, ...workspaceQuery(context) }),
}

function workspaceQuery(context: WorkspaceContextInput): Record<string, string | undefined | null> {
  if (typeof context === 'string') {
    return { package_id: context }
  }
  const normalized = normalizeWorkspaceContext(context)
  return {
    resource_mode: normalized.resourceMode,
    package_id: normalized.packageId,
    factory_session_id: normalized.factorySessionId,
    create_agent_session_id: normalized.createAgentSessionId,
  }
}

function normalizeWorkspaceContext(context: WorkspaceContextInput): WorkspaceRequestContext {
  return context && typeof context === 'object' ? context : {}
}
