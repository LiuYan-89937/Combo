<template>
  <div class="extensions-view">
    <div class="context-bar">
      <div class="context-title">
        <n-text strong>扩展管理</n-text>
        <n-text depth="3" class="context-subtitle">{{ activePackageLabel }}</n-text>
      </div>
      <n-space align="center">
        <n-button @click="refreshCurrentExtensions">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
          刷新
        </n-button>
      </n-space>
    </div>

    <n-alert
      v-if="extensionStore.testResult"
      class="test-result"
      :type="testResultType"
      :title="testResultTitle"
      closable
      @close="extensionStore.setTestResult(null)"
    >
      <div>{{ testResultMessage }}</div>
      <div v-if="testTools.length > 0" class="test-tools">
        <n-tag
          v-for="(tool, index) in testTools"
          :key="tool.name || index"
          size="small"
          :bordered="false"
        >
          {{ tool.name }}
        </n-tag>
      </div>
    </n-alert>

    <n-tabs type="line" animated>
      <n-tab-pane name="mcp" tab="MCP 服务器">
        <div class="tab-content">
          <div class="content-header">
            <n-text>MCP 服务器配置</n-text>
            <n-button type="primary" @click="openAddMcp">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              添加服务器
            </n-button>
          </div>

          <n-list v-if="extensionStore.mcpItems.length > 0" bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.mcpItems" :key="extensionKey(item)">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? '已启用' : '已禁用' }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div class="item-description">
                    {{ item.payload?.description || item.payload?.summary || item.status }}
                  </div>
                  <div class="item-meta">
                    {{ mcpCommandLine(item) }}
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-button
                      size="small"
                      :loading="busyKey === `test:${extensionKey(item)}`"
                      @click="handleTestMcp(item)"
                    >
                      测试连接
                    </n-button>
                    <n-switch
                      :value="item.enabled"
                      :disabled="busyKey === `toggle:${extensionKey(item)}`"
                      @update:value="(value) => handleToggleMcp(item, value)"
                    />
                    <n-dropdown :options="mcpActions" @select="(key) => handleMcpAction(key, item)">
                      <n-button size="small" quaternary circle>
                        <n-icon><EllipsisHorizontal /></n-icon>
                      </n-button>
                    </n-dropdown>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-empty
            v-else
            description="还没有 MCP 服务器"
            style="margin-top: 60px"
          >
            <template #extra>
              <n-button @click="openAddMcp">添加第一个服务器</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>

      <n-tab-pane name="skills" tab="Skills">
        <div class="tab-content">
          <div class="content-header">
            <n-text>Skill 扩展</n-text>
            <n-button type="primary" @click="openAddSkill">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              添加 Skill
            </n-button>
          </div>

          <n-list v-if="extensionStore.skillItems.length > 0" bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.skillItems" :key="extensionKey(item)">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? '已启用' : '已禁用' }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div class="item-description">
                    {{ item.payload?.description || item.payload?.summary || item.status }}
                  </div>
                  <div class="item-meta">
                    {{ item.payload?.path || '未设置路径' }}
                  </div>
                </template>
                <template #action>
                  <n-space>
                    <n-switch
                      :value="item.enabled"
                      :disabled="busyKey === `toggle:${extensionKey(item)}`"
                      @update:value="(value) => handleToggleSkill(item, value)"
                    />
                    <n-dropdown :options="skillActions" @select="(key) => handleSkillAction(key, item)">
                      <n-button size="small" quaternary circle>
                        <n-icon><EllipsisHorizontal /></n-icon>
                      </n-button>
                    </n-dropdown>
                  </n-space>
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-empty
            v-else
            description="还没有 Skill 扩展"
            style="margin-top: 60px"
          >
            <template #extra>
              <n-button @click="openAddSkill">添加第一个 Skill</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>
    </n-tabs>

    <McpConfigModal
      v-model:show="showMcpModal"
      :item="editingMcp"
      @submit="handleSaveMcp"
    />

    <SkillConfigModal
      v-model:show="showSkillModal"
      :item="editingSkill"
      @submit="handleSaveSkill"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NDropdown,
  NEmpty,
  NIcon,
  NList,
  NListItem,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NThing,
  useDialog,
} from 'naive-ui'
import { Add, EllipsisHorizontal, Refresh } from '@vicons/ionicons5'
import { useExtensionStore } from '@/stores/extension'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import SkillConfigModal from '@/components/extensions/SkillConfigModal.vue'
import type { McpServerConfig, SkillConfig } from '@/api/commands'
import type { ExtensionItemView } from '@/types/protocol'

const extensionStore = useExtensionStore()
const commands = useCommand()
const dialog = useDialog()
const resourceContext = useResourceContext()

const showMcpModal = ref(false)
const showSkillModal = ref(false)
const editingMcp = ref<ExtensionItemView | null>(null)
const editingSkill = ref<ExtensionItemView | null>(null)
const busyKey = ref<string | null>(null)

const packageId = computed(() => resourceContext.packageIdForApi.value)

const activePackageLabel = computed(() => {
  return `当前配置目标：${resourceContext.label.value}`
})

const testResultType = computed(() => (
  extensionStore.testResult?.status === 'ok' ? 'success' : 'error'
))
const testResultTitle = computed(() => (
  extensionStore.testResult?.status === 'ok' ? '连接可用' : '连接失败'
))
const testResultMessage = computed(() => String(extensionStore.testResult?.message || '无测试结果'))
const testTools = computed(() => (
  Array.isArray(extensionStore.testResult?.tools) ? extensionStore.testResult.tools : []
))

const mcpActions = [
  { label: '编辑', key: 'edit' },
  { label: '删除', key: 'remove' },
]

const skillActions = [
  { label: '编辑', key: 'edit' },
  { label: '删除', key: 'remove' },
]

function refreshCurrentExtensions() {
  extensionStore.reset()
  editingMcp.value = null
  editingSkill.value = null
  showMcpModal.value = false
  showSkillModal.value = false
  return commands.refreshExtensions(packageId.value)
}

function openAddMcp(): void {
  editingMcp.value = null
  showMcpModal.value = true
}

function openEditMcp(item: ExtensionItemView): void {
  editingMcp.value = item
  showMcpModal.value = true
}

function openAddSkill(): void {
  editingSkill.value = null
  showSkillModal.value = true
}

function openEditSkill(item: ExtensionItemView): void {
  editingSkill.value = item
  showSkillModal.value = true
}

async function handleTestMcp(item: ExtensionItemView): Promise<void> {
  const serverId = String(item.payload?.server_id || '')
  if (!serverId) return
  busyKey.value = `test:${extensionKey(item)}`
  try {
    await commands.testMcp(serverId, packageId.value)
  } finally {
    busyKey.value = null
  }
}

async function handleToggleMcp(item: ExtensionItemView, enabled: boolean): Promise<void> {
  const serverId = String(item.payload?.server_id || '')
  if (!serverId) return
  busyKey.value = `toggle:${extensionKey(item)}`
  try {
    await commands.setMcpEnabled(serverId, enabled, packageId.value)
  } finally {
    busyKey.value = null
  }
}

async function handleToggleSkill(item: ExtensionItemView, enabled: boolean): Promise<void> {
  const skillId = String(item.payload?.skill_id || '')
  if (!skillId) return
  busyKey.value = `toggle:${extensionKey(item)}`
  try {
    await commands.setSkillEnabled(skillId, enabled, packageId.value)
  } finally {
    busyKey.value = null
  }
}

async function handleSaveMcp(config: McpServerConfig): Promise<void> {
  const event = await commands.saveMcp(config, packageId.value)
  if (event) {
    showMcpModal.value = false
    editingMcp.value = null
  }
}

async function handleSaveSkill(config: SkillConfig): Promise<void> {
  const event = await commands.saveSkill(config, packageId.value)
  if (event) {
    showSkillModal.value = false
    editingSkill.value = null
  }
}

function handleMcpAction(key: string, item: ExtensionItemView): void {
  if (key === 'edit') {
    openEditMcp(item)
    return
  }
  if (key === 'remove') {
    confirmRemoveMcp(item)
  }
}

function handleSkillAction(key: string, item: ExtensionItemView): void {
  if (key === 'edit') {
    openEditSkill(item)
    return
  }
  if (key === 'remove') {
    confirmRemoveSkill(item)
  }
}

function confirmRemoveMcp(item: ExtensionItemView): void {
  const serverId = String(item.payload?.server_id || '')
  if (!serverId) return
  dialog.warning({
    title: '删除 MCP 服务器',
    content: `将删除 ${item.name || '这个 MCP 服务器'}，运行中的实例会在下次请求前重新加载配置。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      void commands.removeMcp(serverId, packageId.value)
    },
  })
}

function confirmRemoveSkill(item: ExtensionItemView): void {
  const skillId = String(item.payload?.skill_id || '')
  if (!skillId) return
  dialog.warning({
    title: '删除 Skill',
    content: `将删除 ${item.name || '这个 Skill'}，运行中的实例会在下次请求前重新加载配置。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => {
      void commands.removeSkill(skillId, packageId.value)
    },
  })
}

function extensionKey(item: ExtensionItemView): string {
  return String(item.payload?.server_id || item.payload?.skill_id || item.name || item.kind)
}

function mcpCommandLine(item: ExtensionItemView): string {
  const command = String(item.payload?.command || '')
  const args = Array.isArray(item.payload?.args)
    ? item.payload.args.join(' ')
    : String(item.payload?.args || '')
  return [command, args].filter(Boolean).join(' ') || '未设置命令'
}

watch(
  () => resourceContext.packageId.value,
  () => {
    void refreshCurrentExtensions()
  }
)

onMounted(() => {
  commands.listAgentPackages()
  void refreshCurrentExtensions()
})
</script>

<style scoped>
.extensions-view {
  height: 100%;
  padding: 20px;
  background: var(--n-color);
}

.context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}

.context-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.context-subtitle {
  font-size: 12px;
}

.test-result {
  margin-bottom: 16px;
}

.test-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.tab-content {
  padding: 20px 0;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.extension-list {
  margin-top: 16px;
}

.item-description {
  color: var(--n-text-color-2);
  font-size: 12px;
  line-height: 1.45;
}

.item-meta {
  margin-top: 4px;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
