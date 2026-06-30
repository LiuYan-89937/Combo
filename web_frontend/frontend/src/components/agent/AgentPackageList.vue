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
            <n-button size="small" type="primary" @click.stop="handleRun(pkg)">
              运行
            </n-button>
            <n-button size="small" @click.stop="handleEvolve(pkg)">
              进化
            </n-button>
            <n-dropdown :options="getPackageActions(pkg)" @select="(key) => handleAction(key, pkg)">
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>

          <div class="package-footer">
            <n-tag v-if="pkg.status" size="small" :type="getStatusType(pkg.status)">
              {{ pkg.status }}
            </n-tag>
            <n-text depth="3" style="font-size: 11px">
              {{ formatTime(pkg.updated_at) }}
            </n-text>
          </div>
        </n-card>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NInput, NSelect, NButton, NSpace, NIcon, NEmpty, NCard, NAvatar, NText, NDivider, NTag, NDropdown } from 'naive-ui'
import { Search, Refresh, Build, ChatbubbleEllipses, EllipsisHorizontal } from '@vicons/ionicons5'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import type { AgentPackageView } from '@/stores/agent'

const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const router = useRouter()

const searchQuery = ref('')
const filterStatus = ref<string | null>(null)

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

function handleRefresh() {
  commands.listAgentPackages()
}

function handleSelectPackage(pkg: AgentPackageView) {
  enterPackageContext(pkg, 'run')
}

function handleRun(pkg: AgentPackageView) {
  if (runtimeStore.hasActiveRun) {
    uiStore.addNotification({
      type: 'warning',
      title: '当前会话正在运行',
      message: '等当前回复结束后再运行其他子 Agent。',
      duration: 3000,
    })
    return
  }
  enterPackageContext(pkg, 'run')
  agentStore.enterAgentChat(pkg.package_id)
  runtimeStore.showEmptyAgentPackageSession(pkg.package_id)
  void router.push({ name: 'Factory' })
}

function handleEvolve(pkg: AgentPackageView) {
  enterPackageContext(pkg, 'evolution')
}

function enterPackageContext(pkg: AgentPackageView, purpose: 'run' | 'evolution') {
  agentStore.selectPackage(pkg.package_id)
  workspaceStore.setScope('workdir')
  uiStore.openRightSidebar('workspace')
  commands.selectAgentPackage(pkg.package_id, purpose)
}

function handleAction(key: string, pkg: AgentPackageView) {
  switch (key) {
    case 'delete':
      // TODO: 确认后删除
      break
    case 'export':
      // TODO: 导出
      break
  }
}

function getPackageActions(pkg: AgentPackageView) {
  return [
    { label: '查看详情', key: 'detail' },
    { label: '导出', key: 'export' },
    { label: '删除', key: 'delete' },
  ]
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

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' {
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

onMounted(() => {
  commands.listAgentPackages()
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
</style>
