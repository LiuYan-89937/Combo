/**
 * Knowledge Store
 * 管理知识库源和文档
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
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
  const searchQuery = ref('')

  const selectedSource = computed(() => {
    if (!selectedSourceId.value) return null
    return sources.value.find((s) => s.payload?.source_id === selectedSourceId.value) || null
  })

  function setSources(newSources: KnowledgeSourceView[]): void {
    sources.value = newSources
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

  function setSearchQuery(query: string): void {
    searchQuery.value = query
  }

  function addSource(source: KnowledgeSourceView): void {
    const existingIndex = sources.value.findIndex(
      (s) => s.payload?.source_id === source.payload?.source_id
    )
    if (existingIndex !== -1) {
      sources.value[existingIndex] = source
    } else {
      sources.value.unshift(source)
    }
  }

  function removeSource(sourceId: string): void {
    const index = sources.value.findIndex((s) => s.payload?.source_id === sourceId)
    if (index !== -1) {
      sources.value.splice(index, 1)
    }
    if (selectedSourceId.value === sourceId) {
      selectedSourceId.value = null
    }
  }

  return {
    sources,
    selectedSourceId,
    documents,
    searchResults,
    currentDocument,
    searchQuery,
    selectedSource,
    setSources,
    selectSource,
    setDocuments,
    setSearchResults,
    setCurrentDocument,
    setSearchQuery,
    addSource,
    removeSource,
  }
})
