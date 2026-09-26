import { requestJson, withQuery } from './http'

export interface MemoryContextItemView {
  memory_id: string
  source_scope: 'workspace' | 'user'
  memory_type: string
  kind: string
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

export type MemoryScopeFilter = 'all' | 'user' | 'workspace'

export const memoryApi = {
  query: (query: string, offset = 0, scope: MemoryScopeFilter = 'all', workspaceId: string | null = null) =>
    requestJson<MemoryQueryResponse>(withQuery('/api/memory/query', {
      query,
      offset,
      scope,
      workspace_id: workspaceId || undefined,
    })),
  deleteItem: (memoryId: string) =>
    requestJson<MemoryDeleteResponse>('/api/memory/items', {
      method: 'DELETE',
      body: JSON.stringify({ memory_id: memoryId }),
    }),
}
