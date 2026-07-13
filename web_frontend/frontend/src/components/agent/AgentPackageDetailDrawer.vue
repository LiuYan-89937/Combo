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
            <div class="section-label">{{ t('agentDetail.contextPolicy') }}</div>
            <n-tag size="small" :bordered="false">
              {{ agentPackage.context_contract?.version || t('common.unknown') }}
            </n-tag>
          </div>
          <div class="context-policy-panel">
            <div class="context-config-row">
              <div class="context-config-main">
                <div class="context-config-heading">
                  <div class="item-title">{{ t('agentDetail.contextWindowLimit') }}</div>
                  <div class="context-window-meta">
                    <span>{{ t('agentDetail.contextEffective', { tokens: formatTokens(agentPackage.context_contract?.context_window_tokens) }) }}</span>
                    <span>{{ t('agentDetail.contextEnvDefault', { tokens: formatTokens(agentPackage.context_contract?.context_window_tokens_env) }) }}</span>
                    <span v-if="agentPackage.context_contract?.context_window_tokens_custom">
                      {{ t('agentDetail.contextPackageCustom', { tokens: formatTokens(agentPackage.context_contract.context_window_tokens_custom) }) }}
                    </span>
                  </div>
                </div>
              </div>
              <div class="context-config-control">
                <n-radio-group v-model:value="contextModes.window" size="small" class="context-window-mode soft-segmented-control">
                  <n-radio-button value="env">{{ t('agentDetail.contextFollowEnv') }}</n-radio-button>
                  <n-radio-button value="custom">{{ t('agentDetail.contextCustom') }}</n-radio-button>
                </n-radio-group>
                <n-input-number
                  v-model:value="contextDrafts.window"
                  class="context-window-input"
                  :disabled="contextModes.window !== 'custom'"
                  :min="1000"
                  :show-button="false"
                  :formatter="formatTokenInput"
                  :parser="parseTokenInput"
                  :placeholder="t('agentDetail.contextTokenPlaceholder')"
                />
              </div>
            </div>

            <div class="context-config-row">
              <div class="context-config-main">
                <div class="context-config-heading">
                  <div class="item-title">{{ t('agentDetail.compressionThreshold') }}</div>
                  <div class="context-window-meta">
                    <span>{{ t('agentDetail.contextEffective', { tokens: formatTokens(agentPackage.context_contract?.compression_threshold_tokens) }) }}</span>
                    <span>{{ t('agentDetail.contextEnvDefault', { tokens: formatTokens(agentPackage.context_contract?.compression_threshold_tokens_env) }) }}</span>
                    <span v-if="agentPackage.context_contract?.compression_threshold_tokens_custom">
                      {{ t('agentDetail.contextPackageCustom', { tokens: formatTokens(agentPackage.context_contract.compression_threshold_tokens_custom) }) }}
                    </span>
                  </div>
                </div>
              </div>
              <div class="context-config-control">
                <n-radio-group v-model:value="contextModes.compression" size="small" class="context-window-mode soft-segmented-control">
                  <n-radio-button value="env">{{ t('agentDetail.contextFollowEnv') }}</n-radio-button>
                  <n-radio-button value="custom">{{ t('agentDetail.contextCustom') }}</n-radio-button>
                </n-radio-group>
                <n-input-number
                  v-model:value="contextDrafts.compression"
                  class="context-window-input"
                  :disabled="contextModes.compression !== 'custom'"
                  :min="1000"
                  :show-button="false"
                  :formatter="formatTokenInput"
                  :parser="parseTokenInput"
                  :placeholder="t('agentDetail.contextTokenPlaceholder')"
                />
              </div>
            </div>

            <div class="context-window-help">{{ t('agentDetail.contextPolicyHint') }}</div>
            <n-button
              size="small"
              type="primary"
              class="context-save-button"
              :loading="contextConfigSaving"
              :disabled="!contextConfigDirty"
              @click="emit('saveContextConfig', contextConfigSavePayload())"
            >
              {{ t('common.save') }}
            </n-button>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.models') }}</div>
            <n-tag size="small" :bordered="false">{{ modelBindings.length }}</n-tag>
          </div>
          <n-empty v-if="modelBindings.length === 0" :description="t('agentDetail.noModels')" size="small" />
          <div v-else class="detail-list">
            <div v-for="binding in modelBindings" :key="binding.role" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ binding.role }} · {{ binding.profile_id }}</div>
                <div v-if="binding.reason" class="item-description">{{ binding.reason }}</div>
                <div class="item-meta">
                  {{ binding.selection_source || t('common.auto') }}
                </div>
              </div>
              <n-tag size="small" :bordered="false">
                {{ agentPackage.model_contract?.version || t('common.unknown') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.modelTools') }}</div>
            <n-tag size="small" :bordered="false">{{ modelToolBindings.length }}</n-tag>
          </div>
          <n-empty v-if="modelToolBindings.length === 0" :description="t('agentDetail.noModelTools')" size="small" />
          <div v-else class="detail-list">
            <div v-for="binding in modelToolBindings" :key="binding.tool_id" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ binding.tool_id }} · {{ binding.profile_id }}</div>
                <div v-if="binding.description || binding.reason" class="item-description">
                  {{ binding.description || binding.reason }}
                </div>
                <div class="item-meta">
                  {{ binding.capability || t('common.unknown') }} · {{ binding.selection_source || t('common.auto') }}
                </div>
              </div>
              <n-tag size="small" :bordered="false">
                {{ agentPackage.model_contract?.version || t('common.unknown') }}
              </n-tag>
            </div>
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
            <div class="section-label">运行时资源</div>
            <n-tag size="small" :type="resourceStatusType">{{ resourceStatusLabel }}</n-tag>
          </div>
          <n-empty v-if="resourceItems.length === 0" description="此 Agent 未声明运行时资源" size="small" />
          <div v-else class="detail-list">
            <div v-for="resource in resourceItems" :key="resource.resource_id" class="detail-list-item resource-item">
              <div class="item-main">
                <div class="item-title">{{ resource.resource_id }}</div>
                <div v-if="resource.description" class="item-description">{{ resource.description }}</div>
                <div class="item-meta">{{ resource.required ? '必填' : '可选' }} · {{ resource.used_by.join(', ') || '运行时' }}</div>
                <n-input
                  v-model:value="resourceDrafts[resource.resource_id]"
                  size="small"
                  class="resource-input"
                  :type="resource.secret_fields.length ? 'password' : 'textarea'"
                  :show-password-on="resource.secret_fields.length ? 'click' : undefined"
                  :placeholder="resourceInputHint(resource)"
                />
              </div>
              <div class="resource-actions">
                <n-tag size="small" :type="resource.configured ? 'success' : resource.required ? 'warning' : 'default'">
                  {{ resource.configured ? '已配置' : '待配置' }}
                </n-tag>
                <n-button size="tiny" type="primary" :disabled="!resourceStoreReady" @click="saveResource(resource)">保存</n-button>
                <n-button v-if="resource.configured" size="tiny" quaternary @click="removeResource(resource.resource_id)">移除</n-button>
              </div>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">运行环境</div>
            <n-tag size="small" :type="agentPackage.environment?.status === 'ready' ? 'success' : 'warning'">{{ agentPackage.environment?.status || 'missing' }}</n-tag>
          </div>
          <div class="item-meta">{{ environmentMeta }}</div>
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
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInputNumber,
  NInput,
  NRadioButton,
  NRadioGroup,
  NTag,
} from 'naive-ui'
import { agentPackagesApi, type AgentPackageResourceDescriptorView } from '@/api/agentPackages'
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
  contextConfigSaving: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  initialize: [agentPackage: AgentPackageView]
  shutdown: [agentPackage: AgentPackageView]
  run: [agentPackage: AgentPackageView]
  evolve: [agentPackage: AgentPackageView]
  export: [agentPackage: AgentPackageView]
  saveContextConfig: [payload: { context_window_tokens: number | null; compression_threshold_tokens: number | null }]
}>()

const ready = computed(() => isPackageReady(props.instance))
const { locale, t } = useI18n()
const packageTools = computed<AgentPackageToolView[]>(() => props.agentPackage?.tools || [])
const mcpServers = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.mcp_servers || [])
const skills = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.skills || [])
const knowledgeSources = computed<AgentPackageKnowledgeSourceView[]>(() => props.agentPackage?.knowledge_sources || [])
const resourceItems = ref<AgentPackageResourceDescriptorView[]>([])
const resourceStoreReady = ref(false)
const resourceDrafts = ref<Record<string, string>>({})
const resourceStatusType = computed(() => resourceItems.value.every(item => !item.required || item.configured) ? 'success' : 'warning')
const resourceStatusLabel = computed(() => resourceStoreReady.value ? '运行时配置' : '需要主密钥')
const environmentMeta = computed(() => {
  const environment = props.agentPackage?.environment
  if (!environment) return '尚未生成环境锁定信息'
  const platform = environment.platform?.architecture || ''
  return [environment.image, platform, environment.verified_at].filter(Boolean).join(' · ') || environment.error || '尚未生成环境锁定信息'
})
const modelBindings = computed(() => {
  const bindings = props.agentPackage?.model_contract?.bindings || {}
  return Object.entries(bindings).map(([role, binding]) => ({ role, ...binding }))
})
const modelToolBindings = computed(() => {
  const bindings = props.agentPackage?.model_contract?.tool_bindings || {}
  return Object.entries(bindings).map(([tool_id, binding]) => ({ tool_id, ...binding }))
})
const contextDrafts = ref<{ window: number | null; compression: number | null }>({
  window: null,
  compression: null,
})
const contextModes = ref<{ window: 'env' | 'custom'; compression: 'env' | 'custom' }>({
  window: 'env',
  compression: 'env',
})
const contextConfigDirty = computed(() => {
  const contract = props.agentPackage?.context_contract
  return (
    contextConfigSavePayload().context_window_tokens !== (contract?.context_window_tokens_custom ?? null) ||
    contextConfigSavePayload().compression_threshold_tokens !== (contract?.compression_threshold_tokens_custom ?? null)
  )
})

watch(
  () => props.agentPackage?.context_contract,
  (contract) => {
    contextDrafts.value = {
      window: contract?.context_window_tokens_custom ?? null,
      compression: contract?.compression_threshold_tokens_custom ?? null,
    }
    contextModes.value = {
      window: contract?.context_window_tokens_custom ? 'custom' : 'env',
      compression: contract?.compression_threshold_tokens_custom ? 'custom' : 'env',
    }
  },
  { immediate: true },
)

watch(
  () => [props.show, props.agentPackage?.package_id] as const,
  async ([show, packageId]) => {
    if (!show || !packageId) return
    const payload = await agentPackagesApi.resources(packageId)
    resourceItems.value = payload.resources
    resourceStoreReady.value = payload.key_available
    resourceDrafts.value = Object.fromEntries(payload.resources.map(item => [item.resource_id, '']))
  },
  { immediate: true },
)

function resourceInputHint(resource: AgentPackageResourceDescriptorView): string {
  if (resource.secret_fields.length) return `填写 ${resource.secret_fields.join(', ')} 后保存`
  return '填写 JSON 值或普通文本后保存'
}

async function saveResource(resource: AgentPackageResourceDescriptorView) {
  const packageId = props.agentPackage?.package_id
  if (!packageId) return
  const raw = resourceDrafts.value[resource.resource_id] || ''
  let value: unknown = raw
  try { value = JSON.parse(raw) } catch { /* String values are valid resource input. */ }
  await agentPackagesApi.putResource(packageId, resource.resource_id, value)
  const payload = await agentPackagesApi.resources(packageId)
  resourceItems.value = payload.resources
  resourceDrafts.value[resource.resource_id] = ''
}

async function removeResource(resourceId: string) {
  const packageId = props.agentPackage?.package_id
  if (!packageId) return
  await agentPackagesApi.deleteResource(packageId, resourceId)
  const payload = await agentPackagesApi.resources(packageId)
  resourceItems.value = payload.resources
}

function contextConfigSavePayload(): { context_window_tokens: number | null; compression_threshold_tokens: number | null } {
  return {
    context_window_tokens: contextModes.value.window === 'custom' ? contextDrafts.value.window ?? null : null,
    compression_threshold_tokens: contextModes.value.compression === 'custom' ? contextDrafts.value.compression ?? null : null,
  }
}

function formatTokens(value: number | null | undefined): string {
  if (!value) return t('common.unset')
  return `${formatTokenK(value)}k`
}

function formatTokenInput(value: number | null): string {
  if (!value) return ''
  return formatTokenK(value)
}

function parseTokenInput(input: string): number | null {
  const normalized = input.trim().replace(/[kK]$/u, '')
  if (!normalized) return null
  const parsed = Number(normalized)
  if (!Number.isFinite(parsed) || parsed <= 0) return null
  return Math.round(parsed * 1000)
}

function formatTokenK(value: number): string {
  const kValue = value / 1000
  return Number.isInteger(kValue) ? String(kValue) : String(Math.round(kValue * 10) / 10)
}

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

.resource-item { align-items: flex-start; }
.resource-input { margin-top: var(--app-space-sm); }
.resource-actions { display: grid; justify-items: end; gap: var(--app-space-xs); }

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

.context-policy-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
}

.context-config-row {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.context-config-main {
  min-width: 0;
}

.context-config-heading {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
}

.context-config-control {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  flex-wrap: wrap;
  justify-content: space-between;
}

.context-window-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs) var(--app-space-sm);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
}

.context-window-mode {
  width: fit-content;
}

.context-window-input {
  width: 150px;
}

.context-window-help {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.context-save-button {
  align-self: flex-end;
}

@media (max-width: 560px) {
  .context-config-control {
    align-items: stretch;
    flex-direction: column;
  }

  .context-window-mode,
  .context-window-input {
    width: 100%;
  }
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
