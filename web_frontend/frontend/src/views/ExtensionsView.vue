<template>
  <div class="extensions-view">
    <n-tabs type="line" animated>
      <n-tab-pane name="mcp" tab="MCP 服务器">
        <div class="tab-content">
          <div class="content-header">
            <n-text>MCP 服务器配置</n-text>
            <n-button type="primary" @click="showMcpModal = true">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              添加服务器
            </n-button>
          </div>

          <n-list bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.mcpItems" :key="item.payload?.server_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.payload?.display_name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? '已启用' : '已禁用' }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <n-text depth="3" style="font-size: 12px">
                    {{ item.payload?.command }} {{ item.payload?.args }}
                  </n-text>
                </template>
                <template #action>
                  <n-space>
                    <n-button size="small" @click="handleTestMcp(item)">
                      测试连接
                    </n-button>
                    <n-switch
                      :value="item.enabled"
                      @update:value="(val) => handleToggleMcp(item, val)"
                    />
                    <n-dropdown :options="getMcpActions(item)" @select="(key) => handleMcpAction(key, item)">
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
            v-if="extensionStore.mcpItems.length === 0"
            description="还没有 MCP 服务器"
            style="margin-top: 60px"
          >
            <template #extra>
              <n-button @click="showMcpModal = true">添加第一个服务器</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>

      <n-tab-pane name="skills" tab="Skills">
        <div class="tab-content">
          <div class="content-header">
            <n-text>Skill 扩展</n-text>
          </div>

          <n-list bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.skillItems" :key="item.payload?.skill_id">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.payload?.name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? '已启用' : '已禁用' }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <n-text depth="3" style="font-size: 12px">
                    {{ item.payload?.path }}
                  </n-text>
                </template>
                <template #action>
                  <n-switch
                    :value="item.enabled"
                    @update:value="(val) => handleToggleSkill(item, val)"
                  />
                </template>
              </n-thing>
            </n-list-item>
          </n-list>

          <n-empty
            v-if="extensionStore.skillItems.length === 0"
            description="还没有 Skill 扩展"
            style="margin-top: 60px"
          />
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- MCP 配置弹窗 -->
    <McpConfigModal v-model:show="showMcpModal" @submit="handleSaveMcp" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NTabs, NTabPane, NText, NButton, NIcon, NList, NListItem, NThing, NSpace, NTag, NSwitch, NDropdown, NEmpty } from 'naive-ui'
import { Add, EllipsisHorizontal } from '@vicons/ionicons5'
import { useExtensionStore } from '@/stores/extension'
import { useCommand } from '@/composables/useCommand'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import type { ExtensionItemView } from '@/types/protocol'

const extensionStore = useExtensionStore()
const commands = useCommand()
const showMcpModal = ref(false)

function handleTestMcp(item: ExtensionItemView) {
  const serverId = item.payload?.server_id
  if (serverId) {
    commands.testMcp(serverId)
  }
}

function handleToggleMcp(item: ExtensionItemView, enabled: boolean) {
  const serverId = item.payload?.server_id
  if (serverId) {
    // TODO: 实现启用/禁用
    extensionStore.updateItemEnabled(item, enabled)
  }
}

function handleToggleSkill(item: ExtensionItemView, enabled: boolean) {
  extensionStore.updateItemEnabled(item, enabled)
}

function handleSaveMcp(mcpConfig: any) {
  commands.saveMcp(mcpConfig)
  showMcpModal.value = false
}

function handleMcpAction(key: string, item: ExtensionItemView) {
  switch (key) {
    case 'remove':
      // TODO: 确认后删除
      break
  }
}

function getMcpActions(item: ExtensionItemView) {
  return [
    { label: '编辑', key: 'edit' },
    { label: '删除', key: 'remove' },
  ]
}

onMounted(() => {
  commands.refreshExtensions()
})
</script>

<style scoped>
.extensions-view {
  height: 100%;
  padding: 20px;
  background: var(--n-color);
}

.tab-content {
  padding: 20px 0;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.extension-list {
  margin-top: 16px;
}
</style>
