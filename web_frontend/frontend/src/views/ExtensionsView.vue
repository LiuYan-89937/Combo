<template>
  <div class="extensions-view">
    <div class="context-bar">
      <div class="context-title">
        <n-text strong>{{ t('extensions.title') }}</n-text>
      </div>
      <n-space align="center">
        <ResourceTargetSelector
          v-model="resourceContext.selectedValue.value"
          :options="resourceContext.targetOptions.value"
        />
        <n-button @click="refreshCurrentExtensions">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
          {{ t('common.refresh') }}
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
      <McpTestResultDetails :result="extensionStore.testResult" />
    </n-alert>

    <n-tabs type="line" animated>
      <n-tab-pane name="mcp" :tab="t('extensions.mcpServers')">
        <div class="tab-content">
          <div class="content-header">
            <n-text>{{ t('extensions.mcpConfig') }}</n-text>
            <n-button type="primary" @click="openAddMcp">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              {{ t('extensions.addServer') }}
            </n-button>
          </div>

          <n-list v-if="extensionStore.mcpItems.length > 0" bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.mcpItems" :key="extensionKey(item)">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? t('common.enabled') : t('common.disabled') }}
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
                      {{ t('extensions.testConnection') }}
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
            :description="t('extensions.noMcpServers')"
            class="manager-empty"
          >
            <template #extra>
              <n-button type="primary" @click="openAddMcp">{{ t('extensions.addFirstServer') }}</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>

      <n-tab-pane name="skills" :tab="t('extensions.skillExtensions')">
        <div class="tab-content">
          <section class="skillhub-panel">
            <div class="skillhub-heading">
              <div>
                <n-text strong>{{ t('extensions.skillHubTitle') }}</n-text>
                <div class="item-description">{{ t('extensions.skillHubDescription') }}</div>
              </div>
              <n-tag :type="skillHubCliAvailable ? 'success' : 'error'" :bordered="false">
                {{ skillHubStatusMessage }}
              </n-tag>
            </div>
            <div class="skillhub-search">
              <n-input
                v-model:value="skillHubQuery"
                :placeholder="t('extensions.skillHubSearchPlaceholder')"
                :disabled="!skillHubCliAvailable"
                clearable
                @keyup.enter="handleSkillHubSearch"
              />
              <n-button
                type="primary"
                :disabled="!skillHubCliAvailable || !skillHubQuery.trim()"
                :loading="busyKey === 'skillhub:search'"
                @click="handleSkillHubSearch"
              >
                {{ t('extensions.searchSkillHub') }}
              </n-button>
            </div>
            <div v-if="skillHubItems.length" class="skillhub-results">
              <div v-for="item in skillHubItems" :key="item.install_name || item.name" class="skillhub-result">
                <div class="skillhub-result-content">
                  <div class="skillhub-result-title">
                    <n-text strong>{{ item.name }}</n-text>
                    <n-tag v-if="item.version" size="small" :bordered="false">{{ item.version }}</n-tag>
                  </div>
                  <div class="item-description">{{ item.summary || t('common.noDescription') }}</div>
                </div>
                <n-button
                  size="small"
                  :loading="busyKey === `skillhub:install:${item.install_name || item.name}`"
                  :disabled="Boolean(busyKey)"
                  @click="handleSkillHubInstall(item)"
                >
                  {{ t('extensions.installSkill') }}
                </n-button>
              </div>
            </div>
          </section>

          <div class="content-header">
            <n-text>{{ t('extensions.skillExtensions') }}</n-text>
            <n-button type="primary" @click="openAddSkill">
              <template #icon>
                <n-icon><Add /></n-icon>
              </template>
              {{ t('extensions.addSkill') }}
            </n-button>
          </div>

          <n-list v-if="extensionStore.skillItems.length > 0" bordered class="extension-list">
            <n-list-item v-for="item in extensionStore.skillItems" :key="extensionKey(item)">
              <n-thing>
                <template #header>
                  <n-space align="center">
                    <n-text strong>{{ item.name }}</n-text>
                    <n-tag :type="item.enabled ? 'success' : 'default'" size="small">
                      {{ item.enabled ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </n-space>
                </template>
                <template #description>
                  <div class="item-description">
                    {{ item.payload?.description || item.payload?.summary || item.status }}
                  </div>
                  <div class="item-meta">
                    {{ item.payload?.path || t('extensions.pathUnset') }}
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
            :description="t('extensions.noSkills')"
            class="manager-empty"
          >
            <template #extra>
              <n-button type="primary" @click="openAddSkill">{{ t('extensions.addFirstSkill') }}</n-button>
            </template>
          </n-empty>
        </div>
      </n-tab-pane>

      <n-tab-pane name="permissions" :tab="t('permissions.title')">
        <div class="tab-content">
          <div class="content-header">
            <div>
              <n-text>{{ t('permissions.title') }}</n-text>
              <div class="item-description">{{ t('permissions.description') }}</div>
            </div>
          </div>

          <section class="permission-mode-panel">
            <div class="permission-mode-header">
              <n-text strong>{{ t('permissions.modeTitle') }}</n-text>
              <n-tag size="small" :bordered="false">
                {{ activePermissionModeLabel }}
              </n-tag>
            </div>
            <n-radio-group
              :value="toolPermissionPolicy.mode"
              size="small"
              class="permission-mode-group soft-segmented-control"
              :disabled="busyKey === 'tool-permissions:mode'"
              @update:value="handlePermissionModeChange"
            >
              <n-radio-button
                v-for="option in permissionModeOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </n-radio-button>
            </n-radio-group>
          </section>

          <div v-if="toolPermissionTools.length > 0" class="permission-list">
            <div
              v-for="tool in toolPermissionTools"
              :key="tool.tool_id"
              class="permission-row"
            >
              <div class="permission-tool-main">
                <div class="permission-tool-title">
                  <n-text strong>{{ tool.name }}</n-text>
                  <n-tag size="small" :bordered="false">{{ toolSourceLabel(tool.source) }}</n-tag>
                  <n-tag
                    v-if="hasToolOverride(tool)"
                    size="small"
                    type="info"
                    :bordered="false"
                  >
                    {{ t('permissions.overridden') }}
                  </n-tag>
                </div>
                <div class="item-description">{{ tool.description || t('permissions.noDescription') }}</div>
                <div class="item-meta">{{ tool.tool_id }}</div>
              </div>
              <div class="permission-controls">
                <n-select
                  :value="toolRiskValue(tool)"
                  :options="riskLevelOptions"
                  size="small"
                  class="permission-select"
                  :disabled="busyKey === `permission:${tool.tool_id}`"
                  @update:value="(value) => handleToolRiskChange(tool, String(value))"
                />
                <n-select
                  :value="toolApprovalValue(tool)"
                  :options="approvalOptions"
                  size="small"
                  class="permission-select"
                  :disabled="busyKey === `permission:${tool.tool_id}`"
                  @update:value="(value) => handleToolApprovalChange(tool, String(value))"
                />
                <n-button
                  size="small"
                  quaternary
                  :disabled="!hasToolOverride(tool)"
                  :loading="busyKey === `permission:${tool.tool_id}`"
                  @click="handleResetToolPermission(tool)"
                >
                  {{ t('permissions.reset') }}
                </n-button>
              </div>
            </div>
          </div>

          <n-empty
            v-else
            :description="t('permissions.noTools')"
            class="manager-empty"
          />
        </div>
      </n-tab-pane>
    </n-tabs>

    <McpConfigModal
      v-model:show="showMcpModal"
      :item="editingMcp"
      :busy="busyKey === 'mcp:install'"
      :install-result="mcpInstallResult"
      @submit="handleInstallMcp"
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
  NInput,
  NList,
  NListItem,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NThing,
} from 'naive-ui'
import { Add, EllipsisHorizontal, Refresh } from '@/components/icons'
import { useExtensionsManager } from '@/composables/extensions/useExtensionsManager'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import McpTestResultDetails from '@/components/extensions/McpTestResultDetails.vue'
import SkillConfigModal from '@/components/extensions/SkillConfigModal.vue'
import ResourceTargetSelector from '@/components/resources/ResourceTargetSelector.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()

const {
  activePermissionModeLabel,
  busyKey,
  editingMcp,
  editingSkill,
  extensionKey,
  extensionStore,
  resourceContext,
  handleMcpAction,
  handlePermissionModeChange,
  handleResetToolPermission,
  handleInstallMcp,
  handleSaveSkill,
  handleSkillHubInstall,
  handleSkillHubSearch,
  handleSkillAction,
  handleTestMcp,
  handleToolApprovalChange,
  handleToolRiskChange,
  handleToggleMcp,
  handleToggleSkill,
  hasToolOverride,
  mcpActions,
  mcpCommandLine,
  mcpInstallResult,
  openAddMcp,
  openAddSkill,
  permissionModeOptions,
  refreshCurrentExtensions,
  approvalOptions,
  riskLevelOptions,
  showMcpModal,
  showSkillModal,
  skillActions,
  skillHubCliAvailable,
  skillHubItems,
  skillHubQuery,
  skillHubStatusMessage,
  toolApprovalValue,
  toolPermissionPolicy,
  toolPermissionTools,
  toolRiskValue,
  toolSourceLabel,
  testResultTitle,
  testResultType,
} = useExtensionsManager()
</script>

<style scoped>
.extensions-view {
  height: 100%;
  padding: var(--app-space-xl);
  max-width: var(--app-content-max-width);
  width: 100%;
  margin: 0 auto;
  background: var(--app-surface);
  overflow-y: auto;
}

.context-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--app-space-lg);
  margin-bottom: var(--app-space-lg);
}

.context-title {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.test-result {
  margin-bottom: var(--app-space-lg);
}

.test-tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
  margin-top: var(--app-space-md);
}

.tab-content {
  padding: var(--app-space-xl) 0;
}

.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
  margin-bottom: var(--app-space-xl);
  flex-wrap: wrap;
}

.skillhub-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  padding: var(--app-space-lg);
  margin-bottom: var(--app-space-xl);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
}

.skillhub-heading,
.skillhub-search,
.skillhub-result,
.skillhub-result-title {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
}

.skillhub-heading,
.skillhub-result {
  justify-content: space-between;
}

.skillhub-heading > :first-child,
.skillhub-result-content {
  min-width: 0;
}

.skillhub-search :deep(.n-input) {
  flex: 1;
}

.skillhub-results {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.skillhub-result {
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.skillhub-result-content {
  flex: 1;
}

.skillhub-result-title {
  margin-bottom: var(--app-space-xs);
}

.extension-list {
  margin-top: var(--app-space-lg);
  border-radius: var(--app-radius-lg);
}

.permission-mode-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
  padding: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.permission-mode-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
}

.permission-mode-group {
  align-self: flex-start;
}

.permission-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-lg);
}

.permission-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--app-space-lg);
  padding: var(--app-space-md) var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.permission-tool-main {
  min-width: 0;
}

.permission-tool-title,
.permission-controls {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  flex-wrap: wrap;
}

.permission-tool-title {
  margin-bottom: var(--app-space-xs);
}

.permission-select {
  width: 128px;
}

.item-description {
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  line-height: var(--app-leading-normal);
}

.item-meta {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-sm);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.manager-empty {
  margin-top: 10vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

@media (max-width: 640px) {
  .extensions-view {
    padding: var(--app-space-md);
  }

  .permission-row {
    grid-template-columns: 1fr;
  }

  .permission-controls {
    justify-content: flex-start;
  }
}
</style>
