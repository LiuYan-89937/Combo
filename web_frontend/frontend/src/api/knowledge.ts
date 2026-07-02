import type { KnowledgeSourceInput } from './resourceTypes'
import { requestEvent, requestFormEvent, withQuery } from './http'

export const knowledgeApi = {
  sources: (packageId?: string) => requestEvent(withQuery('/api/knowledge/sources', { package_id: packageId })),
  addSource: (source: KnowledgeSourceInput, packageId?: string) => {
    if (source.files?.length) {
      const formData = new FormData()
      const { files, ...sourcePayload } = source
      formData.append('source', JSON.stringify(sourcePayload))
      if (packageId) formData.append('package_id', packageId)
      files.forEach((item) => {
        formData.append('files', item.file, item.relativePath || item.file.name)
      })
      return requestFormEvent('/api/knowledge/sources/upload', formData)
    }
    return requestEvent('/api/knowledge/sources', {
      method: 'POST',
      body: JSON.stringify({ source, package_id: packageId }),
    })
  },
  documents: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery('/api/knowledge/documents', { source_id: sourceId, package_id: packageId })),
  search: (query: string, sourceId?: string, packageId?: string) =>
    requestEvent(withQuery('/api/knowledge/search', { query, source_id: sourceId, package_id: packageId })),
  removeSource: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}`, { package_id: packageId }), {
      method: 'DELETE',
    }),
  reindexSource: (sourceId: string, packageId?: string) =>
    requestEvent(withQuery(`/api/knowledge/sources/${encodeURIComponent(sourceId)}/reindex`, { package_id: packageId }), {
      method: 'POST',
    }),
}
