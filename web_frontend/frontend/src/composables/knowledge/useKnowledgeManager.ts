import { computed, onMounted, ref, watch } from 'vue'
import { useDialog } from 'naive-ui'
import { DocumentText, FolderOutline, Globe } from '@vicons/ionicons5'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import { useKnowledgeStore } from '@/stores/knowledge'
import type { KnowledgeSourceView } from '@/types/protocol'

export function useKnowledgeManager() {
  const knowledgeStore = useKnowledgeStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useResourceContext()

  const showCreateModal = ref(false)
  const documentsDrawerOpen = ref(false)
  const documentsTitle = ref('')
  const selectedSourceIds = ref<Set<string>>(new Set())
  const busyAction = ref<'delete' | 'reindex' | null>(null)
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
      const event = await commands.reindexKnowledgeSource(sourceId, resourceContext.packageIdForApi.value)
      if (event) {
        commands.refreshKnowledge(resourceContext.packageIdForApi.value)
      }
    } finally {
      busyAction.value = null
      busySourceId.value = null
    }
  }

  function handleCreate(sourceData: any) {
    void commands.addKnowledgeSource(sourceData, resourceContext.packageIdForApi.value)
    showCreateModal.value = false
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
      { label: '查看文档', key: 'documents' },
      { label: '删除', key: 'remove' },
    ]
  }

  async function openDocuments(source: KnowledgeSourceView) {
    const sourceId = sourceIdOf(source)
    if (!sourceId) return
    knowledgeStore.selectSource(sourceId)
    documentsTitle.value = source.name
    documentsDrawerOpen.value = true
    await commands.listKnowledgeDocuments(sourceId, resourceContext.packageIdForApi.value)
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
    const names = targets.map((source) => source.name).join('、')
    dialog.warning({
      title: targets.length > 1 ? '确认批量删除知识源' : '确认删除知识源',
      content: `将删除 ${names}，相关文档和索引会一并移除。这个操作不可撤销。`,
      positiveText: targets.length > 1 ? `删除 ${targets.length} 个` : '删除',
      negativeText: '取消',
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
        const event = await commands.removeKnowledgeSource(sourceId, resourceContext.packageIdForApi.value)
        if (event) {
          deleted += 1
          setSourceSelected(sourceId, false)
        }
      }
      if (deleted > 0) {
        commands.refreshKnowledge(resourceContext.packageIdForApi.value)
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
    () => resourceContext.packageId.value,
    () => {
      resetCurrentKnowledgeView()
      void commands.refreshKnowledge(resourceContext.packageIdForApi.value)
    },
  )

  onMounted(() => {
    commands.listAgentPackages()
    resetCurrentKnowledgeView()
    void commands.refreshKnowledge(resourceContext.packageIdForApi.value)
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
