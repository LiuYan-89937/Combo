import { requestJson, withQuery } from './http'

export const MEMORY_CONTENT_MAX_CHARS = 100
export type MemoryKind = 'constraint' | 'preference' | 'decision' | 'fact' | 'artifact'
export interface MemoryDraft {
  scope: 'workspace' | 'session'
  kind: MemoryKind
  content: string
  workspace_id: string
  session_id: string | null
}

export interface MemoryContextItemView {
  memory_id: string
  revision: number
  source_scope: 'workspace' | 'session'
  memory_type: string
  kind: MemoryKind
  content: string
  score: number
  metadata: Record<string, any>
  namespace: string[]
  updated_at: string | null
}

export interface MemoryQueryResponse {
  package_id: string | null
  namespace: string[]
  namespaces: string[][]
  query: string
  next_offset: number | null
  items: MemoryContextItemView[]
  token_estimate: number
  report: Record<string, any>
}

export interface MemoryDeleteResponse {
  deleted: boolean
  memory_id: string
  package_id: string | null
  namespace: string[]
}

export interface LegacyUserMemoryView {
  memory_id: string
  kind: string
  content: string
  source_session_id: string
}

export interface RecalledMemoryView {
  memory_id: string
  revision: number
  source_scope: 'workspace' | 'session'
  kind: string
  content: string
  origin: 'automatic' | 'explicit'
}

export interface MemoryScopesResponse {
  workspaces: Array<{ workspace_id: string; title: string }>
  sessions: Array<{ session_id: string; workspace_id: string; title: string }>
}

export type MemoryScopeFilter = 'all' | 'workspace' | 'session'

export const memoryApi = {
  createItem: (draft: MemoryDraft) => requestJson('/api/memory/items', { method: 'POST', body: JSON.stringify(draft) }),
  updateItem: (item: MemoryContextItemView, draft: MemoryDraft) => requestJson('/api/memory/items', {
    method: 'PUT', body: JSON.stringify({ ...draft, memory_id: item.memory_id, expected_revision: item.revision }),
  }),
  mergeItems: (items: MemoryContextItemView[], draft: MemoryDraft) => requestJson('/api/memory/merge', {
    method: 'POST', body: JSON.stringify({ ...draft, memories: items.map(item => ({ memory_id: item.memory_id, revision: item.revision })) }),
  }),
  scopes: () => requestJson<MemoryScopesResponse>('/api/memory/scopes'),
  recalled: (sessionId: string) =>
    requestJson<{ turn_id: string | null; items: RecalledMemoryView[] }>(
      withQuery('/api/memory/recalled', { session_id: sessionId }),
    ),
  legacyUserMemories: () =>
    requestJson<{ items: LegacyUserMemoryView[] }>('/api/memory/legacy-user'),
  query: (query: string, offset = 0, scope: MemoryScopeFilter = 'all', workspaceId: string | null = null, sessionId: string | null = null) =>
    requestJson<MemoryQueryResponse>(withQuery('/api/memory/query', {
      query,
      offset,
      scope,
      workspace_id: workspaceId || undefined,
      session_id: sessionId || undefined,
    })),
  deleteItem: (memoryId: string, workspaceId: string, sessionId: string | null) =>
    requestJson<MemoryDeleteResponse>('/api/memory/items', {
      method: 'DELETE',
      body: JSON.stringify({ memory_id: memoryId, workspace_id: workspaceId, session_id: sessionId }),
    }),
}
