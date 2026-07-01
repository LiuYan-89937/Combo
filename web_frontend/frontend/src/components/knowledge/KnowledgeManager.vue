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
} from 'naive-ui'
import { Add, Document, Settings, EllipsisHorizontal } from '@vicons/ionicons5'
import { useKnowledgeManager } from '@/composables/knowledge/useKnowledgeManager'
import KnowledgeSourceFormModal from './KnowledgeSourceFormModal.vue'

const {
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
} = useKnowledgeManager()
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
