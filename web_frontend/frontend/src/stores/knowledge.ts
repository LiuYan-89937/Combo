/**
 * Knowledge Store
 * 管理知识库源和文档
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type {
  KnowledgeSourceView,
  KnowledgeDocumentView,
  KnowledgeSearchResultView,
} from '@/types/protocol'

export const useKnowledgeStore = defineStore('knowledge', () => {
  const sources = ref<KnowledgeSourceView[]>([])
  const selectedSourceId = ref<string | null>(null)
  const documents = ref<KnowledgeDocumentView[]>([])
  const searchResults = ref<KnowledgeSearchResultView[]>([])
  const currentDocument = ref<any | null>(null)

  function setSources(newSources: KnowledgeSourceView[]): void {
    let nextSelectedSourceId = selectedSourceId.value
    let nextDocuments = documents.value
    let nextCurrentDocument = currentDocument.value
    if (
      nextSelectedSourceId &&
      !newSources.some((source) => source.payload?.source_id === nextSelectedSourceId)
    ) {
      nextSelectedSourceId = null
      nextDocuments = []
      nextCurrentDocument = null
    }
    sources.value = newSources
    selectedSourceId.value = nextSelectedSourceId
    documents.value = nextDocuments
    currentDocument.value = nextCurrentDocument
  }

  function selectSource(sourceId: string | null): void {
    selectedSourceId.value = sourceId
    documents.value = []
    currentDocument.value = null
  }

  function setDocuments(newDocuments: KnowledgeDocumentView[]): void {
    documents.value = newDocuments
  }

  function setSearchResults(results: KnowledgeSearchResultView[]): void {
    searchResults.value = results
  }

  function setCurrentDocument(doc: any): void {
    currentDocument.value = doc
  }

  function reset(): void {
    sources.value = []
    selectedSourceId.value = null
    documents.value = []
    searchResults.value = []
    currentDocument.value = null
  }

  return {
    sources,
    selectedSourceId,
    documents,
    searchResults,
    currentDocument,
    setSources,
    selectSource,
    setDocuments,
    setSearchResults,
    setCurrentDocument,
    reset,
  }
})
