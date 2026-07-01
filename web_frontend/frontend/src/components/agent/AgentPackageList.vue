<template>
  <div class="agent-package-list">
    <div class="list-header">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('agents.searchPlaceholder')"
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
          {{ t('agents.deleteSelected', { count: selectedCount }) }}
        </n-button>
        <n-select
          v-model:value="filterStatus"
          :options="statusOptions"
          :placeholder="t('common.status')"
          style="width: 120px"
        />
        <n-button @click="handleRefresh">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
          {{ t('common.refresh') }}
        </n-button>
      </n-space>
    </div>

    <div class="list-content">
      <n-empty
        v-if="filteredPackages.length === 0"
        :description="t('agents.empty')"
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
                {{ pkg.agent_description || t('common.noDescription') }}
              </n-text>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="package-stats">
            <div class="stat-item">
              <n-icon size="16"><Build /></n-icon>
              <span>{{ t('agents.tools', { count: pkg.tool_count || 0 }) }}</span>
            </div>
            <div class="stat-item">
              <n-icon size="16"><ChatbubbleEllipses /></n-icon>
              <span>{{ t('agents.sessions', { count: pkg.session_count || 0 }) }}</span>
            </div>
          </div>

          <div class="package-actions">
            <n-button
              v-if="isPackageReady(pkg)"
              size="small"
              :loading="isInstanceBusy(pkg)"
              @click.stop="handleShutdownInstance(pkg)"
            >
              {{ t('common.close') }}
            </n-button>
            <n-button
              v-else
              size="small"
              :loading="isInstanceBusy(pkg) || isInstanceInitializing(pkg)"
              :disabled="isInstanceInitializing(pkg)"
              @click.stop="handleInitializeInstance(pkg)"
            >
              {{ t('agents.initialize') }}
            </n-button>
            <n-button
              size="small"
              type="primary"
              :disabled="!isPackageReady(pkg)"
              @click.stop="handleRun(pkg)"
            >
              {{ t('agents.run') }}
            </n-button>
            <n-button size="small" @click.stop="handleEvolve(pkg)">
              {{ t('agents.evolve') }}
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

    <AgentPackageDetailDrawer
      v-model:show="detailDrawerOpen"
      :agent-package="detailPackage"
      :instance="detailPackage ? packageInstance(detailPackage) : null"
      :instance-busy="detailPackage ? isInstanceBusy(detailPackage) : false"
      :export-busy="busyAction === 'export'"
      @initialize="handleInitializeInstance"
      @shutdown="handleShutdownInstance"
      @run="handleRun"
      @evolve="handleEvolve"
      @export="handleExport"
    />
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
import AgentPackageDetailDrawer from './AgentPackageDetailDrawer.vue'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import type { AgentPackageView } from '@/stores/agent'
import {
  formatPackageDate as formatTime,
  instanceStatusLabel as packageInstanceStatusLabel,
  instanceStatusType as packageInstanceStatusType,
  isInstanceInitializing as packageInstanceInitializing,
  isPackageReady as packageInstanceReady,
  packageColor as getPackageColor,
  packageDisplayName,
  packageInitial as getPackageInitial,
  statusType as getStatusType,
} from './agentPackagePresentation'

const agentStore = useAgentStore()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const router = useRouter()
const dialog = useDialog()
const { t } = useI18n()

const searchQuery = ref('')
const filterStatus = ref<string | null>(null)
const selectedPackageIds = ref<Set<string>>(new Set())
const detailDrawerOpen = ref(false)
const detailPackage = ref<AgentPackageView | null>(null)
const busyAction = ref<'delete' | 'export' | 'instance' | null>(null)
const busyInstancePackageId = ref<string | null>(null)

const statusOptions = computed(() => [
  { label: t('common.all'), value: null },
  { label: t('agents.statusReady'), value: 'ready' },
  { label: t('agents.statusRunning'), value: 'running' },
])

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
      title: t('agents.instanceNotReadyTitle'),
      message: t('agents.instanceNotReadyMessage'),
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
    { label: t('common.details'), key: 'detail' },
    { label: t('common.export'), key: 'export' },
    { label: t('common.delete'), key: 'delete' },
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
    title: targets.length > 1 ? t('agents.confirmBulkDeleteTitle') : t('agents.confirmDeleteTitle'),
    content: t('agents.confirmDeleteContent', { names }),
    positiveText: targets.length > 1 ? t('agents.confirmBulkPositive', { count: targets.length }) : t('common.delete'),
    negativeText: t('common.cancel'),
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
        title: t('agents.deleteCompleteTitle'),
        message: t('agents.deleteCompleteMessage', { count: deleted }),
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

function packageInstance(pkg: AgentPackageView) {
  return agentStore.packageInstance(pkg.package_id)
}

function isPackageReady(pkg: AgentPackageView): boolean {
  return packageInstanceReady(packageInstance(pkg))
}

function isInstanceInitializing(pkg: AgentPackageView): boolean {
  return packageInstanceInitializing(packageInstance(pkg))
}

function isInstanceBusy(pkg: AgentPackageView): boolean {
  return busyAction.value === 'instance' && busyInstancePackageId.value === pkg.package_id
}

function instanceStatusLabel(pkg: AgentPackageView): string {
  return packageInstanceStatusLabel(packageInstance(pkg))
}

function getInstanceStatusType(pkg: AgentPackageView): 'default' | 'success' | 'warning' | 'error' | 'info' {
  return packageInstanceStatusType(packageInstance(pkg))
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
</style>
