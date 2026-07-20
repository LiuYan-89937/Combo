<template>
  <div class="knowledge-manager">
    <div class="manager-header">
      <div class="manager-title">
        <n-text strong>{{ t('knowledge.title') }}</n-text>
        <n-text depth="3" class="context-label">
          {{ t('resource.currentContext', { label: resourceContext.label.value }) }}
        </n-text>
      </div>
      <n-space>
        <n-button
          v-if="selectedCount > 0"
          :loading="busyAction === 'delete'"
          @click="confirmDeleteSources(selectedSources)"
        >
          {{ t('knowledge.deleteSelected', { count: selectedCount }) }}
        </n-button>
        <n-button type="primary" @click="showCreateModal = true">
          <template #icon>
            <n-icon><Add /></n-icon>
          </template>
          {{ t('knowledge.add') }}
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
            <div class="source-avatar" :style="{ color: getSourceColor(source) }">
              <n-icon size="22">
                <component :is="getSourceIcon(source)" />
              </n-icon>
            </div>
            <div class="source-info">
              <n-text strong class="source-name">{{ sourceDisplayName(source) }}</n-text>
              <n-tag :type="getStatusType(source.status)" size="small" class="source-status">
                {{ sourceStatusLabel(source.status) }}
              </n-tag>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="source-stats">
            <div v-if="source.documentCount != null" class="stat-item">
              <n-icon size="14" class="stat-icon"><Document /></n-icon>
              <span class="stat-text">{{ t('knowledge.documents', { count: source.documentCount }) }}</span>
            </div>
            <div v-if="source.mode" class="stat-item">
              <n-icon size="14" class="stat-icon"><Settings /></n-icon>
              <span class="stat-text">{{ source.mode }}</span>
            </div>
          </div>

          <div v-if="ingestionOf(source)" class="ingestion-progress">
            <div class="ingestion-progress-header">
              <n-text depth="3">{{ ingestionMessage(source) }}</n-text>
              <n-text depth="3">{{ ingestionOf(source)?.percent }}%</n-text>
            </div>
            <n-progress
              type="line"
              :percentage="ingestionOf(source)?.percent || 0"
              :status="ingestionProgressStatus(source)"
              :show-indicator="false"
              :height="6"
              border-radius="3"
            />
            <n-text v-if="ingestionOf(source)?.error" type="error" class="ingestion-error">
              {{ ingestionOf(source)?.error }}
            </n-text>
          </div>

          <div class="source-actions">
            <n-button
              size="small"
              :loading="busyAction === 'reindex' && busySourceId === sourceIdOf(source)"
              @click.stop="handleReindex(source)"
            >
              {{ t('knowledge.reindex') }}
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
        :description="t('knowledge.empty')"
        class="manager-empty"
      >
        <template #icon>
          <n-icon size="56" class="manager-empty-icon">
            <Library />
          </n-icon>
        </template>
        <template #extra>
          <n-button type="primary" @click="showCreateModal = true">{{ t('knowledge.addFirst') }}</n-button>
        </template>
      </n-empty>
    </n-scrollbar>

    <!-- 创建知识源弹窗 -->
    <KnowledgeSourceFormModal
      v-model:show="showCreateModal"
      :submitting="creatingSource"
      @submit="handleCreate"
    />

    <n-drawer v-model:show="documentsDrawerOpen" :width="520" placement="right">
      <n-drawer-content :title="t('knowledge.documentsTitle')" closable>
        <div class="documents-panel">
          <div class="documents-title">{{ documentsTitle }}</div>
          <n-empty
            v-if="knowledgeStore.documents.length === 0"
            :description="t('knowledge.noDocuments')"
            size="small"
          />
          <n-list v-else>
            <n-list-item
              v-for="document in knowledgeStore.documents"
              :key="document.documentId || document.payload?.document_id || document.title"
            >
              <div class="document-item">
                <div class="document-title">
                  {{ document.title || document.name || t('knowledge.document') }}
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
  NProgress,
  NScrollbar,
  NSpace,
  NTag,
  NText,
} from 'naive-ui'
import { Add, Document, Library, Settings, EllipsisHorizontal } from '@/components/icons'
import { useKnowledgeManager } from '@/composables/knowledge/useKnowledgeManager'
import KnowledgeSourceFormModal from './KnowledgeSourceFormModal.vue'
import { useI18n } from '@/composables/useI18n'
import type { KnowledgeSourceView } from '@/types/protocol'
import type { KnowledgeIngestionProgress } from '@/stores/knowledge'

const { t } = useI18n()

const {
  busyAction,
  busySourceId,
  creatingSource,
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

function sourceDisplayName(source: KnowledgeSourceView): string {
  return source.name || t('knowledge.sourceFallback')
}

function sourceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: t('agents.statusReady'),
    indexing: t('knowledge.updating'),
    failed: t('run.failed'),
  }
  return labels[status] || status || t('common.unknown')
}

function ingestionOf(source: KnowledgeSourceView): KnowledgeIngestionProgress | null {
  const sourceId = sourceIdOf(source)
  return sourceId ? knowledgeStore.ingestionBySource[sourceId] || null : null
}

function ingestionMessage(source: KnowledgeSourceView): string {
  const ingestion = ingestionOf(source)
  if (!ingestion) return ''
  if (ingestion.status === 'completed') return t('knowledge.ingestionCompleted')
  if (ingestion.status === 'failed') return t('knowledge.ingestionFailed')
  if (ingestion.status === 'queued') return t('knowledge.ingestionQueued')
  return ingestion.phase
    ? t('knowledge.ingestionPhase', { phase: ingestion.phase })
    : t('knowledge.ingestionRunning')
}

function ingestionProgressStatus(source: KnowledgeSourceView): 'default' | 'success' | 'error' | 'warning' {
  const status = ingestionOf(source)?.status
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'cancelled') return 'warning'
  return 'default'
}
</script>

<style scoped>
.knowledge-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--app-space-xl);
  max-width: var(--app-content-max-width);
  width: 100%;
  margin: 0 auto;
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
  flex-wrap: wrap;
}

.manager-title {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.context-label {
  font-size: var(--app-font-sm);
}

.source-list {
  flex: 1;
  min-height: 0;
  margin: 0 calc(var(--app-space-xs) * -1);
  padding: 0 var(--app-space-xs) var(--app-space-lg);
}

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--app-space-lg);
}

.source-card {
  cursor: pointer;
  transition: transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  border-radius: var(--app-radius-lg);
  animation: app-fade-in-up 0.5s var(--app-transition-spring) both;
  will-change: transform;
}

.source-card:nth-child(1) { animation-delay: 0.08s; }
.source-card:nth-child(2) { animation-delay: 0.16s; }
.source-card:nth-child(3) { animation-delay: 0.24s; }
.source-card:nth-child(4) { animation-delay: 0.32s; }
.source-card:nth-child(5) { animation-delay: 0.40s; }
.source-card:nth-child(n+6) { animation-delay: 0.48s; }

.source-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--app-shadow-lg);
}

.source-card:active {
  transform: translateY(-2px) scale(0.98);
  transition-duration: 0.12s;
}

.source-header {
  display: flex;
  gap: var(--app-space-md);
  align-items: center;
}

.source-select {
  flex-shrink: 0;
}

.source-avatar {
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.source-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.source-name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--app-leading-tight);
}

.source-status {
  align-self: flex-start;
}

.source-stats {
  display: flex;
  gap: var(--app-space-lg);
  margin: var(--app-space-md) 0;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  font-size: var(--app-font-sm);
  color: var(--app-text-secondary);
  line-height: 1.4;
  min-width: 0;
}

.stat-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.stat-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  flex-wrap: wrap;
}

.ingestion-progress {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  margin-top: var(--app-space-sm);
}

.ingestion-progress-header {
  display: flex;
  justify-content: space-between;
  gap: var(--app-space-sm);
  font-size: var(--app-font-xs);
}

.ingestion-error {
  font-size: var(--app-font-xs);
  overflow-wrap: anywhere;
}

.documents-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
}

.documents-title {
  font-size: var(--app-font-xl);
  font-weight: 600;
}

.document-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
}

.document-title {
  font-size: var(--app-font-lg);
  font-weight: 500;
}

.document-meta,
.document-uri {
  font-size: var(--app-font-sm);
  color: var(--app-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.manager-empty {
  margin-top: 12vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.manager-empty-icon {
  display: block;
  color: var(--app-text-muted);
  opacity: 0.55;
  line-height: 1;
}

@media (max-width: 640px) {
  .knowledge-manager {
    padding: var(--app-space-md);
  }
  .source-grid {
    grid-template-columns: 1fr;
    gap: var(--app-space-md);
  }
}
</style>
