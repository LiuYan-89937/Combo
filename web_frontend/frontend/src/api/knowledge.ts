import type { KnowledgeSourceInput, WorkspaceContextInput } from './resourceTypes'
import { requestEvent, requestFormEvent, requestJson, withQuery } from './http'
import { packageResourceContextPayload } from './resourceContext'

export interface KnowledgeRetrievalSettings {
  revision: number
  lexical_limit: number
  vector_limit: number
  result_limit: number
  rrf_k: number
  vector_minimum_similarity: number
  lexical_weight: number
  vector_weight: number
  updated_at: string | null
}

export const knowledgeApi = {
  settings: () => requestJson<KnowledgeRetrievalSettings>('/api/knowledge/settings'),
  updateSettings: (settings: KnowledgeRetrievalSettings) => {
    const { revision, updated_at: _updatedAt, ...payload } = settings
    return requestJson<KnowledgeRetrievalSettings>('/api/knowledge/settings', {
      method: 'PATCH',
      body: JSON.stringify({ expected_revision: revision, ...payload }),
    })
  },
  sources: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/knowledge/sources', packageResourceContextPayload(context))),
  addSource: (
    source: KnowledgeSourceInput,
    context?: WorkspaceContextInput,
    onUploadProgress?: (percent: number) => void,
  ) => {
    const resourceContext = packageResourceContextPayload(context)
    if (source.files?.length) {
      const formData = new FormData()
      const { files, ...sourcePayload } = source
      formData.append('source', JSON.stringify(sourcePayload))
      if (resourceContext.package_id) formData.append('package_id', resourceContext.package_id)
      if (resourceContext.resource_mode) formData.append('resource_mode', resourceContext.resource_mode)
      files.forEach((item) => {
        formData.append('files', item.file, item.relativePath || item.file.name)
      })
      return requestFormEvent('/api/knowledge/sources/upload', formData, onUploadProgress)
    }
    return requestEvent('/api/knowledge/sources', {
      method: 'POST',
      body: JSON.stringify({ source, ...resourceContext }),
    })
  },
  documents: (sourceId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/knowledge/documents', { source_id: sourceId, ...packageResourceContextPayload(context) })),
  document: (documentId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/knowledge/document', { document_id: documentId, ...packageResourceContextPayload(context) })),
  search: (query: string, sourceId?: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/knowledge/search', { query, source_id: sourceId, ...packageResourceContextPayload(context) })),
  removeSource: (sourceId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}`, packageResourceContextPayload(context)), {
      method: 'DELETE',
    }),
  reindexSource: (sourceId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}/reindex`, packageResourceContextPayload(context)), {
      method: 'POST',
    }),
}
