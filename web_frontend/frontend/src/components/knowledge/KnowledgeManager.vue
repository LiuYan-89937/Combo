<template>
  <div class="knowledge-manager">
    <div class="manager-header">
      <div class="manager-title">
        <n-text strong>知识源</n-text>
        <n-text depth="3" class="context-label">当前上下文：{{ resourceContext.label.value }}</n-text>
      </div>
      <n-space>
        <n-button
          v-if="selectedCount > 0"
          :loading="busyAction === 'delete'"
          @click="confirmDeleteSources(selectedSources)"
        >
          删除已选 {{ selectedCount }}
        </n-button>
        <n-button type="primary" @click="showCreateModal = true">
          <template #icon>
            <n-icon><Add /></n-icon>
          </template>
          添加知识源
        </n-button>
      </n-space>
    </div>

    <n-scrollbar class="source-list">
      <div class="source-grid">
        <n-card
          v-for="source in knowledgeStore.sources"
          :key="sourceKey(source)"
          hoverable
          class="source-card"
          @click="handleSelectSource(source)"
        >
          <div class="source-header">
            <n-checkbox
              v-if="sourceIdOf(source)"
              class="source-select"
              :checked="selectedSourceIds.has(sourceIdOf(source)!)"
              @click.stop
              @update:checked="(checked) => setSourceSelected(sourceIdOf(source)!, checked)"
            />
            <n-icon size="32" :color="getSourceColor(source)">
              <component :is="getSourceIcon(source)" />
            </n-icon>
            <div class="source-info">
              <n-text strong>{{ source.name }}</n-text>
              <n-tag :type="getStatusType(source.status)" size="small">
                {{ source.status }}
              </n-tag>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="source-stats">
            <div v-if="source.documentCount != null" class="stat-item">
              <n-icon size="16"><Document /></n-icon>
              <span>{{ source.documentCount }} 文档</span>
            </div>
            <div v-if="source.mode" class="stat-item">
              <n-icon size="16"><Settings /></n-icon>
              <span>{{ source.mode }}</span>
            </div>
          </div>

          <div class="source-actions">
            <n-button
              size="small"
              :loading="busyAction === 'reindex' && busySourceId === sourceIdOf(source)"
              @click.stop="handleReindex(source)"
            >
              重新索引
            </n-button>
            <n-dropdown
              :options="getSourceActions(source)"
              @select="(key) => handleAction(key, source)"
            >
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>
        </n-card>
      </div>

      <n-empty
        v-if="knowledgeStore.sources.length === 0"
        description="还没有知识源"
        style="margin-top: 60px"
      >
        <template #extra>
          <n-button @click="showCreateModal = true">添加第一个知识源</n-button>
        </template>
      </n-empty>
    </n-scrollbar>

    <!-- 创建知识源弹窗 -->
    <KnowledgeSourceFormModal
      v-model:show="showCreateModal"
      @submit="handleCreate"
    />

    <n-drawer v-model:show="documentsDrawerOpen" :width="520" placement="right">
      <n-drawer-content title="知识源文档" closable>
        <div class="documents-panel">
          <div class="documents-title">{{ documentsTitle }}</div>
          <n-empty
            v-if="knowledgeStore.documents.length === 0"
            description="没有可查看的文档"
            size="small"
          />
          <n-list v-else>
            <n-list-item
              v-for="document in knowledgeStore.documents"
              :key="document.documentId || document.payload?.document_id || document.title"
            >
              <div class="document-item">
                <div class="document-title">
                  {{ document.title || document.name || '文档' }}
                </div>
                <div class="document-meta">
                  {{ document.documentType || document.kind || 'document' }}
                </div>
                <div v-if="document.uri" class="document-uri">
                  {{ document.uri }}
                </div>
              </div>
            </n-list-item>
          </n-list>
        </div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import {
  NButton,
  NCard,
  NCheckbox,
  NDivider,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NEmpty,
  NIcon,
  NList,
  NListItem,
  NScrollbar,
  NSpace,
  NTag,
  NText,
  useDialog,
} from 'naive-ui'
import { Add, Document, Settings, EllipsisHorizontal, FolderOutline, Globe, DocumentText } from '@vicons/ionicons5'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import KnowledgeSourceFormModal from './KnowledgeSourceFormModal.vue'
import type { KnowledgeSourceView } from '@/types/protocol'

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

function getSourceActions(source: KnowledgeSourceView) {
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
  const types: Record<string, any> = {
    ready: 'success',
    indexing: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}

watch(
  () => resourceContext.packageId.value,
  () => {
    resetCurrentKnowledgeView()
    void commands.refreshKnowledge(resourceContext.packageIdForApi.value)
  }
)

onMounted(() => {
  commands.listAgentPackages()
  resetCurrentKnowledgeView()
  void commands.refreshKnowledge(resourceContext.packageIdForApi.value)
})

function resetCurrentKnowledgeView() {
  selectedSourceIds.value = new Set()
  documentsDrawerOpen.value = false
  documentsTitle.value = ''
  knowledgeStore.reset()
}
</script>

<style scoped>
.knowledge-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
}

.manager-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.context-label {
  font-size: 12px;
}

.source-list {
  flex: 1;
  min-height: 0;
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.source-card {
  cursor: pointer;
  transition: transform 0.2s;
}

.source-card:hover {
  transform: translateY(-2px);
}

.source-header {
  display: flex;
  gap: 12px;
  align-items: center;
}

.source-select {
  flex-shrink: 0;
}

.source-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.source-stats {
  display: flex;
  gap: 16px;
  margin: 12px 0;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--n-text-color-2);
}

.source-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.documents-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.documents-title {
  font-size: 16px;
  font-weight: 600;
}

.document-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.document-title {
  font-size: 14px;
  font-weight: 500;
}

.document-meta,
.document-uri {
  font-size: 12px;
  color: var(--n-text-color-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
