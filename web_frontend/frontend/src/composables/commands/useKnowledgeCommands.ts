import { knowledgeApi } from '@/api/knowledge'
import type { KnowledgeSourceInput } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useKnowledgeCommands() {
  const transport = useCommandTransport()

  const refreshKnowledge = (packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.sources(packageId))
  }

  const addKnowledgeSource = (source: KnowledgeSourceInput, packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.addSource(source, packageId))
  }

  const listKnowledgeDocuments = (sourceId: string, packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.documents(sourceId, packageId))
  }

  const searchKnowledge = (query: string, sourceId?: string, packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.search(query, sourceId, packageId))
  }

  const removeKnowledgeSource = (sourceId: string, packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.removeSource(sourceId, packageId))
  }

  const reindexKnowledgeSource = (sourceId: string, packageId?: string) => {
    return transport.applyEventRequest(knowledgeApi.reindexSource(sourceId, packageId))
  }

  return {
    refreshKnowledge,
    addKnowledgeSource,
    listKnowledgeDocuments,
    searchKnowledge,
    removeKnowledgeSource,
    reindexKnowledgeSource,
  }
}
