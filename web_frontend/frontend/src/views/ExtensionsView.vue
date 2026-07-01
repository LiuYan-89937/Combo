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
} from 'naive-ui'
import { Add, EllipsisHorizontal, Refresh } from '@vicons/ionicons5'
import { useExtensionsManager } from '@/composables/extensions/useExtensionsManager'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import SkillConfigModal from '@/components/extensions/SkillConfigModal.vue'

const {
  activePackageLabel,
  busyKey,
  editingMcp,
  editingSkill,
  extensionKey,
  extensionStore,
  handleMcpAction,
  handleSaveMcp,
  handleSaveSkill,
  handleSkillAction,
  handleTestMcp,
  handleToggleMcp,
  handleToggleSkill,
  mcpActions,
  mcpCommandLine,
  openAddMcp,
  openAddSkill,
  refreshCurrentExtensions,
  showMcpModal,
  showSkillModal,
  skillActions,
  testResultMessage,
  testResultTitle,
  testResultType,
  testTools,
} = useExtensionsManager()
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
