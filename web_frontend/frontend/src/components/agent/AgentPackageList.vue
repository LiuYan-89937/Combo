<template>
  <div class="agent-package-list">
    <div class="list-header">
      <n-input
        v-model:value="searchQuery"
        placeholder="搜索 Agent 包..."
        clearable
      >
        <template #prefix>
          <n-icon><Search /></n-icon>
        </template>
      </n-input>

      <n-space>
        <n-button
          v-if="selectedCount > 0"
          :loading="busyAction === 'delete'"
          @click="confirmDeletePackages(selectedPackages)"
        >
          删除已选 {{ selectedCount }}
        </n-button>
        <n-select
          v-model:value="filterStatus"
          :options="statusOptions"
          placeholder="状态"
          style="width: 120px"
        />
        <n-button @click="handleRefresh">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
          刷新
        </n-button>
      </n-space>
    </div>

    <div class="list-content">
      <n-empty
        v-if="filteredPackages.length === 0"
        description="没有 Agent 包"
        style="margin-top: 60px"
      />

      <div v-else class="package-grid">
        <n-card
          v-for="pkg in filteredPackages"
          :key="pkg.package_id"
          hoverable
          class="package-card"
          @click="handleSelectPackage(pkg)"
        >
          <div class="package-header">
            <n-checkbox
              class="package-select"
              :checked="selectedPackageIds.has(pkg.package_id)"
              @click.stop
              @update:checked="(checked) => setPackageSelected(pkg.package_id, checked)"
            />
            <n-avatar :size="48" :style="{ background: getPackageColor(pkg) }">
              {{ getPackageInitial(pkg) }}
            </n-avatar>
            <div class="package-info">
              <n-text strong>{{ pkg.agent_name || pkg.name || pkg.package_id }}</n-text>
              <n-text depth="3" style="font-size: 12px">
                {{ pkg.agent_description || '无描述' }}
              </n-text>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="package-stats">
            <div class="stat-item">
              <n-icon size="16"><Build /></n-icon>
              <span>{{ pkg.tool_count || 0 }} 工具</span>
            </div>
            <div class="stat-item">
              <n-icon size="16"><ChatbubbleEllipses /></n-icon>
              <span>{{ pkg.session_count || 0 }} 会话</span>
            </div>
          </div>

          <div class="package-actions">
            <n-button
              v-if="isPackageReady(pkg)"
              size="small"
              :loading="isInstanceBusy(pkg)"
              @click.stop="handleShutdownInstance(pkg)"
            >
              关闭
            </n-button>
            <n-button
              v-else
              size="small"
              :loading="isInstanceBusy(pkg) || isInstanceInitializing(pkg)"
              :disabled="isInstanceInitializing(pkg)"
              @click.stop="handleInitializeInstance(pkg)"
            >
              初始化
            </n-button>
            <n-button
              size="small"
              type="primary"
              :disabled="!isPackageReady(pkg)"
              @click.stop="handleRun(pkg)"
            >
              运行
            </n-button>
            <n-button size="small" @click.stop="handleEvolve(pkg)">
              进化
            </n-button>
            <n-dropdown :options="getPackageActions()" @select="(key) => handleAction(key, pkg)">
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>

          <div class="package-footer">
            <n-tag v-if="pkg.status" size="small" :type="getStatusType(pkg.status)">
              {{ pkg.status }}
            </n-tag>
            <n-tag size="small" :type="getInstanceStatusType(pkg)">
              {{ instanceStatusLabel(pkg) }}
            </n-tag>
            <n-text depth="3" style="font-size: 11px">
              {{ formatTime(pkg.updated_at) }}
            </n-text>
          </div>
        </n-card>
      </div>
    </div>

    <n-drawer v-model:show="detailDrawerOpen" :width="460" placement="right">
      <n-drawer-content title="Agent 包详情" closable>
        <div v-if="detailPackage" class="detail-panel">
          <section class="detail-section">
            <div class="detail-title">{{ packageDisplayName(detailPackage) }}</div>
            <div class="detail-description">
              {{ detailPackage.agent_description || '无描述' }}
            </div>
          </section>

          <section class="detail-section detail-grid">
            <div class="detail-row">
              <span>状态</span>
              <n-tag size="small" :type="getStatusType(detailPackage.status || '')">
                {{ detailPackage.status || '未知' }}
              </n-tag>
            </div>
            <div class="detail-row">
              <span>工具</span>
              <strong>{{ detailPackage.tool_count || 0 }}</strong>
            </div>
            <div class="detail-row">
              <span>会话</span>
              <strong>{{ detailPackage.session_count || 0 }}</strong>
            </div>
            <div class="detail-row">
              <span>更新时间</span>
              <strong>{{ formatFullTime(detailPackage.updated_at) }}</strong>
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

          <section v-if="detailPackage.extensions_error || detailPackage.knowledge_error" class="detail-section">
            <div class="section-label">详情读取提示</div>
            <div v-if="detailPackage.extensions_error" class="detail-note">
              MCP / Skill 配置读取失败：{{ detailPackage.extensions_error }}
            </div>
            <div v-if="detailPackage.knowledge_error" class="detail-note">
              知识库详情读取失败：{{ detailPackage.knowledge_error }}
            </div>
          </section>

          <section v-if="detailPackage.error" class="detail-section">
            <div class="section-label">状态说明</div>
            <div class="detail-note">
              {{ detailPackage.error }}
            </div>
          </section>

          <div class="detail-actions">
            <n-button
              v-if="isPackageReady(detailPackage)"
              :loading="isInstanceBusy(detailPackage)"
              @click="handleShutdownInstance(detailPackage)"
            >
              关闭实例
            </n-button>
            <n-button
              v-else
              :loading="isInstanceBusy(detailPackage)"
              @click="handleInitializeInstance(detailPackage)"
            >
              初始化实例
            </n-button>
            <n-button type="primary" :disabled="!isPackageReady(detailPackage)" @click="handleRun(detailPackage)">运行</n-button>
            <n-button @click="handleEvolve(detailPackage)">进化</n-button>
            <n-button :loading="busyAction === 'export'" @click="handleExport(detailPackage)">
              导出
            </n-button>
          </div>
        </div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAvatar,
  NButton,
  NCard,
  NCheckbox,
  NDivider,
  NDrawer,
  NDrawerContent,
  NDropdown,
  NEmpty,
  NIcon,
  NInput,
  NSelect,
  NSpace,
  NTag,
  NText,
  useDialog,
} from 'naive-ui'
import { Search, Refresh, Build, ChatbubbleEllipses, EllipsisHorizontal } from '@vicons/ionicons5'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import type { AgentPackageView } from '@/stores/agent'
import type {
  AgentPackageExtensionView,
  AgentPackageKnowledgeSourceView,
  AgentPackageToolView,
} from '@/stores/agent'

const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const router = useRouter()
const dialog = useDialog()

const searchQuery = ref('')
const filterStatus = ref<string | null>(null)
const selectedPackageIds = ref<Set<string>>(new Set())
const detailDrawerOpen = ref(false)
const detailPackage = ref<AgentPackageView | null>(null)
const busyAction = ref<'delete' | 'export' | 'instance' | null>(null)
const busyInstancePackageId = ref<string | null>(null)

const statusOptions = [
  { label: '全部', value: null },
  { label: '就绪', value: 'ready' },
  { label: '运行中', value: 'running' },
]

const filteredPackages = computed(() => {
  let packages = agentStore.agentPackages

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    packages = packages.filter(
      (p) =>
        p.agent_name?.toLowerCase().includes(query) ||
        p.name?.toLowerCase().includes(query) ||
        p.agent_description?.toLowerCase().includes(query)
    )
  }

  if (filterStatus.value) {
    packages = packages.filter((p) => p.status === filterStatus.value)
  }

  return packages
})
const selectedPackages = computed(() => {
  return agentStore.agentPackages.filter((pkg) => selectedPackageIds.value.has(pkg.package_id))
})
const selectedCount = computed(() => selectedPackages.value.length)
const packageTools = computed<AgentPackageToolView[]>(() => detailPackage.value?.tools || [])
const mcpServers = computed<AgentPackageExtensionView[]>(() => detailPackage.value?.mcp_servers || [])
const skills = computed<AgentPackageExtensionView[]>(() => detailPackage.value?.skills || [])
const knowledgeSources = computed<AgentPackageKnowledgeSourceView[]>(() => detailPackage.value?.knowledge_sources || [])

function handleRefresh() {
  commands.listAgentPackages()
  commands.listAgentPackageInstances()
}

function handleSelectPackage(pkg: AgentPackageView) {
  enterPackageContext(pkg, 'run')
}

function handleRun(pkg: AgentPackageView) {
  if (!isPackageReady(pkg)) {
    uiStore.addNotification({
      type: 'warning',
      title: '实例未初始化',
      message: '请先初始化这个子 Agent 实例。',
      duration: 3000,
    })
    return
  }
  void enterPackageContext(pkg, 'run')
  agentStore.enterAgentChat(pkg.package_id)
  runtimeStore.showEmptyAgentPackageSession(pkg.package_id)
  void router.push({ name: 'Factory' })
}

async function handleInitializeInstance(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'instance'
  busyInstancePackageId.value = pkg.package_id
  try {
    await commands.initializeAgentPackage(pkg.package_id)
  } finally {
    busyAction.value = null
    busyInstancePackageId.value = null
  }
}

async function handleShutdownInstance(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'instance'
  busyInstancePackageId.value = pkg.package_id
  try {
    await commands.shutdownAgentPackageInstance(pkg.package_id)
  } finally {
    busyAction.value = null
    busyInstancePackageId.value = null
  }
}

function handleEvolve(pkg: AgentPackageView) {
  agentStore.leaveAgentChat()
  runtimeStore.enterFactoryConversation('evolve_agent', pkg.package_id)
  void enterPackageContext(pkg, 'evolution').then(() => {
    void router.push({ name: 'Evolution' })
  })
}

function enterPackageContext(pkg: AgentPackageView, purpose: 'run' | 'evolution') {
  agentStore.selectPackage(pkg.package_id)
  workspaceStore.setScope('package')
  uiStore.openRightSidebar('workspace')
  return commands.selectAgentPackage(pkg.package_id, purpose)
}

function handleAction(key: string, pkg: AgentPackageView) {
  switch (key) {
    case 'detail':
      detailPackage.value = pkg
      detailDrawerOpen.value = true
      break
    case 'delete':
      confirmDeletePackages([pkg])
      break
    case 'export':
      void handleExport(pkg)
      break
  }
}

function getPackageActions() {
  return [
    { label: '查看详情', key: 'detail' },
    { label: '导出', key: 'export' },
    { label: '删除', key: 'delete' },
  ]
}

function setPackageSelected(packageId: string, checked: boolean) {
  const next = new Set(selectedPackageIds.value)
  if (checked) {
    next.add(packageId)
  } else {
    next.delete(packageId)
  }
  selectedPackageIds.value = next
}

function confirmDeletePackages(packages: AgentPackageView[]) {
  const targets = packages.filter((pkg) => pkg.package_id)
  if (targets.length === 0 || busyAction.value) return
  const names = targets.map(packageDisplayName).join('、')
  dialog.warning({
    title: targets.length > 1 ? '确认批量删除 Agent 包' : '确认删除 Agent 包',
    content: `将删除 ${names}，相关运行中的实例会被关闭。这个操作不可撤销。`,
    positiveText: targets.length > 1 ? `删除 ${targets.length} 个` : '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      void deletePackages(targets)
    },
  })
}

async function deletePackages(packages: AgentPackageView[]) {
  busyAction.value = 'delete'
  let deleted = 0
  try {
    for (const pkg of packages) {
      const event = await commands.deleteAgentPackage(pkg.package_id)
      if (event) {
        deleted += 1
        setPackageSelected(pkg.package_id, false)
      }
    }
    if (deleted > 0) {
      uiStore.addNotification({
        type: 'success',
        title: '删除完成',
        message: `已删除 ${deleted} 个 Agent 包。`,
        duration: 3000,
      })
    }
  } finally {
    busyAction.value = null
  }
}

async function handleExport(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'export'
  try {
    await commands.exportAgentPackage(pkg)
  } finally {
    busyAction.value = null
  }
}

function packageDisplayName(pkg: AgentPackageView): string {
  return pkg.agent_name || pkg.name || '未命名 Agent'
}

function packageInstance(pkg: AgentPackageView) {
  return agentStore.packageInstance(pkg.package_id)
}

function isPackageReady(pkg: AgentPackageView): boolean {
  return packageInstance(pkg)?.ready === true
}

function isInstanceInitializing(pkg: AgentPackageView): boolean {
  return packageInstance(pkg)?.status === 'initializing'
}

function isInstanceBusy(pkg: AgentPackageView): boolean {
  return busyAction.value === 'instance' && busyInstancePackageId.value === pkg.package_id
}

function instanceStatusLabel(pkg: AgentPackageView): string {
  const instance = packageInstance(pkg)
  if (!instance) return '未初始化'
  if (instance.error) return '实例异常'
  if (instance.status === 'initializing') return '初始化中'
  if (instance.ready) return instance.active_request_count ? `运行中 ${instance.active_request_count}` : '已就绪'
  return '未初始化'
}

function getInstanceStatusType(pkg: AgentPackageView): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const instance = packageInstance(pkg)
  if (instance?.error) return 'error'
  if (instance?.status === 'initializing') return 'info'
  if (instance?.active_request_count) return 'info'
  if (instance?.ready) return 'success'
  return 'default'
}

function getPackageInitial(pkg: AgentPackageView): string {
  const name = pkg.agent_name || pkg.name || pkg.package_id
  return name.charAt(0).toUpperCase()
}

function getPackageColor(pkg: AgentPackageView): string {
  const colors = ['#18a058', '#2080f0', '#f0a020', '#d03050']
  const hash = pkg.package_id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0)
  return colors[hash % colors.length]
}

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, any> = {
    ready: 'success',
    running: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}

function formatTime(timestamp: string | null): string {
  if (!timestamp) return '未知'
  const date = new Date(timestamp)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
}

function formatFullTime(timestamp: string | null): string {
  if (!timestamp) return '未知'
  return new Date(timestamp).toLocaleString('zh-CN')
}

function extensionKey(item: AgentPackageExtensionView): string {
  const payloadId = item.payload?.server_id || item.payload?.skill_id
  return String(payloadId || item.name)
}

function toolMeta(tool: AgentPackageToolView): string {
  return tool.concurrent === false ? '串行执行' : '可并发执行'
}

function extensionDescription(item: AgentPackageExtensionView): string {
  return String(item.payload?.description || item.summary || '').trim()
}

function mcpMeta(server: AgentPackageExtensionView): string {
  const payload = server.payload || {}
  const envCount = Array.isArray(payload.env_keys) ? payload.env_keys.length : 0
  const parts = [
    server.transport || payload.transport,
    server.scope,
    envCount > 0 ? `环境变量 ${envCount} 项` : null,
    payload.timeout_seconds ? `${payload.timeout_seconds} 秒超时` : null,
  ].filter(Boolean)
  return parts.join(' · ') || 'MCP 服务器'
}

function skillMeta(skill: AgentPackageExtensionView): string {
  const payload = skill.payload || {}
  const resourceCount = Number(payload.resource_count || 0)
  const scriptCount = Number(payload.script_count || 0)
  const parts = [
    skill.scope,
    resourceCount > 0 ? `${resourceCount} 个资源` : null,
    scriptCount > 0 ? `${scriptCount} 个脚本` : null,
  ].filter(Boolean)
  return parts.join(' · ') || 'Skill'
}

function knowledgeMeta(source: AgentPackageKnowledgeSourceView): string {
  const parts = [
    source.kind,
    source.mode,
    source.document_count != null ? `${source.document_count} 文档` : null,
    source.updated_at ? `更新于 ${formatFullTime(source.updated_at)}` : null,
  ].filter(Boolean)
  return parts.join(' · ') || '知识源'
}

function knowledgeSamples(source: AgentPackageKnowledgeSourceView): string {
  const titles = (source.sample_titles || []).filter(Boolean).slice(0, 3)
  return titles.length > 0 ? `样例：${titles.join('、')}` : ''
}

onMounted(() => {
  handleRefresh()
})
</script>

<style scoped>
.agent-package-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
}

.list-header {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.list-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.package-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.package-card {
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
}

.package-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.package-header {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.package-select {
  margin-top: 14px;
  flex-shrink: 0;
}

.package-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.package-stats {
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

.package-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.package-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--n-border-color);
}

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
