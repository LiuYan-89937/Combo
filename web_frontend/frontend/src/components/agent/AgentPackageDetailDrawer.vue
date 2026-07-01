<template>
  <n-drawer :show="show" :width="460" placement="right" @update:show="emit('update:show', $event)">
    <n-drawer-content title="Agent 包详情" closable>
      <div v-if="agentPackage" class="detail-panel">
        <section class="detail-section">
          <div class="detail-title">{{ packageDisplayName(agentPackage) }}</div>
          <div class="detail-description">
            {{ agentPackage.agent_description || '无描述' }}
          </div>
        </section>

        <section class="detail-section detail-grid">
          <div class="detail-row">
            <span>状态</span>
            <n-tag size="small" :type="statusType(agentPackage.status || '')">
              {{ agentPackage.status || '未知' }}
            </n-tag>
          </div>
          <div class="detail-row">
            <span>工具</span>
            <strong>{{ agentPackage.tool_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>会话</span>
            <strong>{{ agentPackage.session_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>更新时间</span>
            <strong>{{ formatPackageDateTime(agentPackage.updated_at) }}</strong>
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
            <span>知识源</span>
            <strong>{{ knowledgeSources.length }}</strong>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">包内工具</div>
            <n-tag size="small" :bordered="false">{{ packageTools.length }}</n-tag>
          </div>
          <n-empty v-if="packageTools.length === 0" description="未配置包内工具" size="small" />
          <div v-else class="detail-list">
            <div v-for="tool in packageTools" :key="tool.id || tool.name" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ tool.name }}</div>
                <div v-if="tool.description" class="item-description">{{ tool.description }}</div>
                <div class="item-meta">{{ toolMeta(tool) }}</div>
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
          <n-empty v-if="mcpServers.length === 0" description="未配置 MCP" size="small" />
          <div v-else class="detail-list">
            <div v-for="server in mcpServers" :key="extensionKey(server)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ server.name }}</div>
                <div v-if="extensionDescription(server)" class="item-description">
                  {{ extensionDescription(server) }}
                </div>
                <div class="item-meta">{{ mcpMeta(server) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="server.enabled === false ? 'default' : 'success'">
                {{ server.enabled === false ? '停用' : '启用' }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">Skill</div>
            <n-tag size="small" :bordered="false">{{ skills.length }}</n-tag>
          </div>
          <n-empty v-if="skills.length === 0" description="未配置 Skill" size="small" />
          <div v-else class="detail-list">
            <div v-for="skill in skills" :key="extensionKey(skill)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ skill.name }}</div>
                <div v-if="extensionDescription(skill)" class="item-description">
                  {{ extensionDescription(skill) }}
                </div>
                <div class="item-meta">{{ skillMeta(skill) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="skill.enabled === false ? 'default' : 'success'">
                {{ skill.enabled === false ? '停用' : '启用' }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">知识库</div>
            <n-tag size="small" :bordered="false">{{ knowledgeSources.length }}</n-tag>
          </div>
          <n-empty v-if="knowledgeSources.length === 0" description="未配置知识源" size="small" />
          <div v-else class="detail-list">
            <div
              v-for="source in knowledgeSources"
              :key="source.source_id || source.name"
              class="detail-list-item knowledge-item"
            >
              <div class="item-main">
                <div class="item-title">{{ source.name }}</div>
                <div class="item-description">
                  {{ knowledgeMeta(source) }}
                </div>
                <div v-if="source.uri" class="item-uri">{{ source.uri }}</div>
                <div v-if="knowledgeSamples(source)" class="item-meta">
                  {{ knowledgeSamples(source) }}
                </div>
              </div>
              <n-tag size="small" :bordered="false" :type="source.status === 'ready' ? 'success' : 'default'">
                {{ source.status || '未知' }}
              </n-tag>
            </div>
          </div>
        </section>

        <section v-if="agentPackage.extensions_error || agentPackage.knowledge_error" class="detail-section">
          <div class="section-label">详情读取提示</div>
          <div v-if="agentPackage.extensions_error" class="detail-note">
            MCP / Skill 配置读取失败：{{ agentPackage.extensions_error }}
          </div>
          <div v-if="agentPackage.knowledge_error" class="detail-note">
            知识库详情读取失败：{{ agentPackage.knowledge_error }}
          </div>
        </section>

        <section v-if="agentPackage.error" class="detail-section">
          <div class="section-label">状态说明</div>
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
            关闭实例
          </n-button>
          <n-button
            v-else
            :loading="instanceBusy"
            @click="emit('initialize', agentPackage)"
          >
            初始化实例
          </n-button>
          <n-button type="primary" :disabled="!ready" @click="emit('run', agentPackage)">运行</n-button>
          <n-button @click="emit('evolve', agentPackage)">进化</n-button>
          <n-button :loading="exportBusy" @click="emit('export', agentPackage)">
            导出
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
const packageTools = computed<AgentPackageToolView[]>(() => props.agentPackage?.tools || [])
const mcpServers = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.mcp_servers || [])
const skills = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.skills || [])
const knowledgeSources = computed<AgentPackageKnowledgeSourceView[]>(() => props.agentPackage?.knowledge_sources || [])
</script>

<style scoped>
.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.detail-section {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.detail-section:last-child {
  border-bottom: 0;
}

.detail-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.detail-description {
  margin-top: 6px;
  color: var(--n-text-color-2);
  line-height: 1.5;
}

.detail-grid {
  display: grid;
  gap: 10px;
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;
}

.detail-row span,
.section-label {
  color: var(--n-text-color-2);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.detail-list-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
}

.item-main {
  min-width: 0;
  flex: 1;
}

.item-title {
  color: var(--n-text-color-1);
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-description {
  margin-top: 4px;
  color: var(--n-text-color-2);
  font-size: 12px;
  line-height: 1.45;
}

.item-meta {
  margin-top: 4px;
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 1.4;
}

.item-uri {
  margin-top: 4px;
  color: var(--n-text-color-3);
  font-size: 11px;
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
  gap: 8px;
}

.detail-note {
  margin-top: 8px;
  padding: 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  color: var(--n-text-color-2);
  font-size: 13px;
  line-height: 1.5;
}

.detail-note + .detail-note {
  margin-top: 8px;
}
</style>
