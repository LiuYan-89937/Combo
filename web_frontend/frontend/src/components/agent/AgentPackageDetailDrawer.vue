<template>
  <n-drawer :show="show" :width="460" placement="right" @update:show="emit('update:show', $event)">
    <n-drawer-content :title="t('agentDetail.title')" closable>
      <div v-if="agentPackage" class="detail-panel">
        <section class="detail-section">
          <div class="detail-title">{{ packageDisplayName(agentPackage, t) }}</div>
          <div class="detail-description">
            {{ agentPackage.agent_description || t('common.noDescription') }}
          </div>
        </section>

        <section class="detail-section detail-grid">
          <div class="detail-row">
            <span>{{ t('common.status') }}</span>
            <n-tag size="small" :type="statusType(agentPackage.status || '')">
              {{ packageStatusLabel(agentPackage.status) }}
            </n-tag>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.tools') }}</span>
            <strong>{{ agentPackage.tool_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.sessions') }}</span>
            <strong>{{ agentPackage.session_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.updatedAt') }}</span>
            <strong>{{ formatPackageDateTime(agentPackage.updated_at, locale, t) }}</strong>
          </div>
          <div class="detail-row">
            <span>MCP</span>
            <strong>{{ mcpServers.length }}</strong>
          </div>
          <div class="detail-row">
            <span>Skill</span>
            <strong>{{ skills.length }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.knowledgeSources') }}</span>
            <strong>{{ knowledgeSources.length }}</strong>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.packageTools') }}</div>
            <n-tag size="small" :bordered="false">{{ packageTools.length }}</n-tag>
          </div>
          <n-empty v-if="packageTools.length === 0" :description="t('agentDetail.noPackageTools')" size="small" />
          <div v-else class="detail-list">
            <div v-for="tool in packageTools" :key="tool.id || tool.name" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ tool.name }}</div>
                <div v-if="tool.description" class="item-description">{{ tool.description }}</div>
                <div class="item-meta">{{ toolMeta(tool, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false">{{ tool.risk_level || 'low' }}</n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">MCP</div>
            <n-tag size="small" :bordered="false">{{ mcpServers.length }}</n-tag>
          </div>
          <n-empty v-if="mcpServers.length === 0" :description="t('agentDetail.noMcp')" size="small" />
          <div v-else class="detail-list">
            <div v-for="server in mcpServers" :key="extensionKey(server)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ server.name }}</div>
                <div v-if="extensionDescription(server)" class="item-description">
                  {{ extensionDescription(server) }}
                </div>
                <div class="item-meta">{{ mcpMeta(server, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="server.enabled === false ? 'default' : 'success'">
                {{ server.enabled === false ? t('agentDetail.disabled') : t('agentDetail.enabled') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">Skill</div>
            <n-tag size="small" :bordered="false">{{ skills.length }}</n-tag>
          </div>
          <n-empty v-if="skills.length === 0" :description="t('agentDetail.noSkill')" size="small" />
          <div v-else class="detail-list">
            <div v-for="skill in skills" :key="extensionKey(skill)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ skill.name }}</div>
                <div v-if="extensionDescription(skill)" class="item-description">
                  {{ extensionDescription(skill) }}
                </div>
                <div class="item-meta">{{ skillMeta(skill, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="skill.enabled === false ? 'default' : 'success'">
                {{ skill.enabled === false ? t('agentDetail.disabled') : t('agentDetail.enabled') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.knowledgeBase') }}</div>
            <n-tag size="small" :bordered="false">{{ knowledgeSources.length }}</n-tag>
          </div>
          <n-empty v-if="knowledgeSources.length === 0" :description="t('agentDetail.noKnowledge')" size="small" />
          <div v-else class="detail-list">
            <div
              v-for="source in knowledgeSources"
              :key="source.source_id || source.name"
              class="detail-list-item knowledge-item"
            >
              <div class="item-main">
                <div class="item-title">{{ source.name }}</div>
                <div class="item-description">
                  {{ knowledgeMeta(source, locale, t) }}
                </div>
                <div v-if="source.uri" class="item-uri">{{ source.uri }}</div>
                <div v-if="knowledgeSamples(source, t)" class="item-meta">
                  {{ knowledgeSamples(source, t) }}
                </div>
              </div>
              <n-tag size="small" :bordered="false" :type="source.status === 'ready' ? 'success' : 'default'">
                {{ packageStatusLabel(source.status) }}
              </n-tag>
            </div>
          </div>
        </section>

        <section v-if="agentPackage.extensions_error || agentPackage.knowledge_error" class="detail-section">
          <div class="section-label">{{ t('agentDetail.readHint') }}</div>
          <div v-if="agentPackage.extensions_error" class="detail-note">
            {{ t('agentDetail.extensionsReadFailed', { error: agentPackage.extensions_error }) }}
          </div>
          <div v-if="agentPackage.knowledge_error" class="detail-note">
            {{ t('agentDetail.knowledgeReadFailed', { error: agentPackage.knowledge_error }) }}
          </div>
        </section>

        <section v-if="agentPackage.error" class="detail-section">
          <div class="section-label">{{ t('agentDetail.statusNote') }}</div>
          <div class="detail-note">
            {{ agentPackage.error }}
          </div>
        </section>

        <div class="detail-actions">
          <n-button
            v-if="ready"
            :loading="instanceBusy"
            @click="emit('shutdown', agentPackage)"
          >
            {{ t('agentDetail.shutdown') }}
          </n-button>
          <n-button
            v-else
            :loading="instanceBusy"
            @click="emit('initialize', agentPackage)"
          >
            {{ t('agentDetail.initialize') }}
          </n-button>
          <n-button type="primary" :disabled="!ready" @click="emit('run', agentPackage)">{{ t('agents.run') }}</n-button>
          <n-button @click="emit('evolve', agentPackage)">{{ t('agents.evolve') }}</n-button>
          <n-button :loading="exportBusy" @click="emit('export', agentPackage)">
            {{ t('common.export') }}
          </n-button>
        </div>
      </div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NTag,
} from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import type {
  AgentPackageExtensionView,
  AgentPackageInstanceView,
  AgentPackageKnowledgeSourceView,
  AgentPackageToolView,
  AgentPackageView,
} from '@/stores/agent'
import {
  extensionDescription,
  extensionKey,
  formatPackageDateTime,
  isPackageReady,
  knowledgeMeta,
  knowledgeSamples,
  mcpMeta,
  packageDisplayName,
  skillMeta,
  statusType,
  toolMeta,
} from './agentPackagePresentation'

const props = defineProps<{
  show: boolean
  agentPackage: AgentPackageView | null
  instance: AgentPackageInstanceView | null
  instanceBusy: boolean
  exportBusy: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  initialize: [agentPackage: AgentPackageView]
  shutdown: [agentPackage: AgentPackageView]
  run: [agentPackage: AgentPackageView]
  evolve: [agentPackage: AgentPackageView]
  export: [agentPackage: AgentPackageView]
}>()

const ready = computed(() => isPackageReady(props.instance))
const { locale, t } = useI18n()
const packageTools = computed<AgentPackageToolView[]>(() => props.agentPackage?.tools || [])
const mcpServers = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.mcp_servers || [])
const skills = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.skills || [])
const knowledgeSources = computed<AgentPackageKnowledgeSourceView[]>(() => props.agentPackage?.knowledge_sources || [])

function packageStatusLabel(status: string | null | undefined): string {
  const value = status || ''
  const labels: Record<string, string> = {
    ready: t('agents.statusReady'),
    running: t('agents.statusRunning'),
    failed: t('run.failed'),
    initializing: t('agentDetail.initializing'),
  }
  return labels[value] || value || t('common.unknown')
}
</script>

<style scoped>
.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section {
  padding-bottom: var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.detail-section:last-child {
  border-bottom: 0;
}

.detail-title {
  font-size: var(--app-font-xl);
  font-weight: 600;
  color: var(--app-text-strong);
  letter-spacing: -0.01em;
}

.detail-description {
  margin-top: var(--app-space-xs);
  color: var(--app-text-secondary);
  line-height: var(--app-leading-normal);
}

.detail-grid {
  display: grid;
  gap: var(--app-space-sm);
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  font-size: var(--app-font-md);
}

.detail-row span,
.section-label {
  color: var(--app-text-secondary);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-sm);
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.detail-list-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.detail-list-item:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface-hover);
}

.item-main {
  min-width: 0;
  flex: 1;
}

.item-title {
  color: var(--app-text);
  font-size: var(--app-font-md);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-description {
  margin-top: var(--app-space-xs);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  line-height: var(--app-leading-normal);
}

.item-meta {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
}

.item-uri {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-item {
  align-items: flex-start;
}

.detail-actions {
  display: flex;
  gap: var(--app-space-sm);
}

.detail-note {
  margin-top: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-size: var(--app-font-md);
  line-height: var(--app-leading-normal);
}

.detail-note + .detail-note {
  margin-top: var(--app-space-sm);
}
</style>
