import { computed, onMounted, ref, watch } from 'vue'
import { useDialog } from 'naive-ui'
import { DocumentText, FolderOutline, Globe } from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KnowledgeSourceView } from '@/types/protocol'

export function useKnowledgeManager() {
  const knowledgeStore = useKnowledgeStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useResourceContext()
  const { t } = useI18n()

  const showCreateModal = ref(false)
  const documentsDrawerOpen = ref(false)
  const documentsTitle = ref('')
  const selectedSourceIds = ref<Set<string>>(new Set())
  const busyAction = ref<'create' | 'delete' | 'reindex' | null>(null)
  const busySourceId = ref<string | null>(null)

  const selectedSources = computed(() => {
    return knowledgeStore.sources.filter((source) => {
      const sourceId = sourceIdOf(source)
      return Boolean(sourceId && selectedSourceIds.value.has(sourceId))
    })
  })
  const selectedCount = computed(() => selectedSources.value.length)

  function handleSelectSource(source: KnowledgeSourceView) {
    const sourceId = source.payload?.source_id
    if (sourceId) {
      knowledgeStore.selectSource(sourceId)
    }
  }

  async function handleReindex(source: KnowledgeSourceView) {
    const sourceId = sourceIdOf(source)
    if (!sourceId || busyAction.value) return
    busyAction.value = 'reindex'
    busySourceId.value = sourceId
    try {
      const event = await commands.reindexKnowledgeSource(sourceId, resourceContext.workspaceContext.value)
      if (event) {
        void commands.refreshKnowledge(resourceContext.workspaceContext.value)
      }
    } finally {
      busyAction.value = null
      busySourceId.value = null
    }
  }

  async function handleCreate(sourceData: any) {
    if (busyAction.value) return
    busyAction.value = 'create'
    try {
      const event = await commands.addKnowledgeSource(sourceData, resourceContext.workspaceContext.value)
      if (event) {
        showCreateModal.value = false
      }
    } finally {
      busyAction.value = null
    }
  }

  function handleAction(key: string, source: KnowledgeSourceView) {
    switch (key) {
      case 'documents':
        void openDocuments(source)
        break
      case 'remove':
        confirmDeleteSources([source])
        break
    }
  }

  function getSourceActions(_source: KnowledgeSourceView) {
    return [
      { label: t('knowledge.viewDocuments'), key: 'documents' },
      { label: t('common.delete'), key: 'remove' },
    ]
  }

  async function openDocuments(source: KnowledgeSourceView) {
    const sourceId = sourceIdOf(source)
    if (!sourceId) return
    knowledgeStore.selectSource(sourceId)
    documentsTitle.value = source.name || t('knowledge.sourceFallback')
    documentsDrawerOpen.value = true
    await commands.listKnowledgeDocuments(sourceId, resourceContext.workspaceContext.value)
  }

  function setSourceSelected(sourceId: string, checked: boolean) {
    const next = new Set(selectedSourceIds.value)
    if (checked) {
      next.add(sourceId)
    } else {
      next.delete(sourceId)
    }
    selectedSourceIds.value = next
  }

  function confirmDeleteSources(sources: KnowledgeSourceView[]) {
    const targets = sources.filter((source) => sourceIdOf(source))
    if (targets.length === 0 || busyAction.value) return
    const names = targets.map((source) => source.name || t('knowledge.sourceFallback')).join('、')
    dialog.warning({
      title: targets.length > 1 ? t('knowledge.confirmBulkDeleteTitle') : t('knowledge.confirmDeleteTitle'),
      content: t('knowledge.confirmDeleteContent', { names }),
      positiveText: targets.length > 1 ? t('knowledge.confirmBulkPositive', { count: targets.length }) : t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: () => {
        void deleteSources(targets)
      },
    })
  }

  async function deleteSources(sources: KnowledgeSourceView[]) {
    busyAction.value = 'delete'
    let deleted = 0
    try {
      for (const source of sources) {
        const sourceId = sourceIdOf(source)
        if (!sourceId) continue
        const event = await commands.removeKnowledgeSource(sourceId, resourceContext.workspaceContext.value)
        if (event) {
          deleted += 1
          setSourceSelected(sourceId, false)
        }
      }
      if (deleted > 0) {
        void commands.refreshKnowledge(resourceContext.workspaceContext.value)
      }
    } finally {
      busyAction.value = null
    }
  }

  function resetCurrentKnowledgeView() {
    selectedSourceIds.value = new Set()
    documentsDrawerOpen.value = false
    documentsTitle.value = ''
    knowledgeStore.reset()
  }

  watch(
    () => resourceContext.workspaceContextKey.value,
    () => {
      resetCurrentKnowledgeView()
      void commands.refreshKnowledge(resourceContext.workspaceContext.value)
    },
  )

  onMounted(() => {
    commands.listAgentPackages()
    resetCurrentKnowledgeView()
    void commands.refreshKnowledge(resourceContext.workspaceContext.value)
  })

  return {
    busyAction,
    busySourceId,
    confirmDeleteSources,
    documentsDrawerOpen,
    documentsTitle,
    getSourceActions,
    getSourceColor,
    getSourceIcon,
    getStatusType,
    handleAction,
    handleCreate,
    handleReindex,
    handleSelectSource,
    knowledgeStore,
    resourceContext,
    selectedCount,
    selectedSourceIds,
    selectedSources,
    setSourceSelected,
    showCreateModal,
    sourceIdOf,
    sourceKey,
  }
}

function sourceIdOf(source: KnowledgeSourceView): string | null {
  const sourceId = source.payload?.source_id
  return sourceId ? String(sourceId) : null
}

function sourceKey(source: KnowledgeSourceView): string {
  return sourceIdOf(source) || source.name
}

function getSourceIcon(source: KnowledgeSourceView) {
  const kind = source.payload?.kind
  if (kind === 'folder' || kind === 'file') return FolderOutline
  if (kind === 'url') return Globe
  return DocumentText
}

function getSourceColor(source: KnowledgeSourceView): string {
  const colors = ['#18a058', '#2080f0', '#f0a020']
  const kind = source.payload?.kind || ''
  return colors[kind.length % colors.length]
}

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
    ready: 'success',
    indexing: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}
