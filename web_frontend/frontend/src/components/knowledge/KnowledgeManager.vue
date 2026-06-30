<template>
  <div class="knowledge-manager">
    <div class="manager-header">
      <n-text strong>知识源</n-text>
      <n-button type="primary" @click="showCreateModal = true">
        <template #icon>
          <n-icon><Add /></n-icon>
        </template>
        添加知识源
      </n-button>
    </div>

    <n-scrollbar class="source-list">
      <div class="source-grid">
        <n-card
          v-for="source in knowledgeStore.sources"
          :key="source.name"
          hoverable
          class="source-card"
          @click="handleSelectSource(source)"
        >
          <div class="source-header">
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
            <n-button size="small" @click.stop="handleReindex(source)">
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NText, NButton, NIcon, NScrollbar, NCard, NTag, NDivider, NDropdown, NEmpty } from 'naive-ui'
import { Add, Document, Settings, EllipsisHorizontal, FolderOutline, Globe, DocumentText } from '@vicons/ionicons5'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useCommand } from '@/composables/useCommand'
import KnowledgeSourceFormModal from './KnowledgeSourceFormModal.vue'
import type { KnowledgeSourceView } from '@/types/protocol'

const knowledgeStore = useKnowledgeStore()
const commands = useCommand()
const showCreateModal = ref(false)

function handleSelectSource(source: KnowledgeSourceView) {
  const sourceId = source.payload?.source_id
  if (sourceId) {
    knowledgeStore.selectSource(sourceId)
  }
}

function handleReindex(source: KnowledgeSourceView) {
  // TODO: 重新索引
}

function handleCreate(sourceData: any) {
  commands.addKnowledgeSource(sourceData)
  showCreateModal.value = false
}

function handleAction(key: string, source: KnowledgeSourceView) {
  const sourceId = source.payload?.source_id
  switch (key) {
    case 'remove':
      // TODO: 确认后删除
      break
  }
}

function getSourceActions(source: KnowledgeSourceView) {
  return [
    { label: '查看文档', key: 'documents' },
    { label: '删除', key: 'remove' },
  ]
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

onMounted(() => {
  commands.refreshKnowledge()
})
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
  margin-bottom: 20px;
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
</style>
