<template>
  <aside class="right-sidebar" :style="{ width: `${uiStore.rightSidebarWidth}px` }">
    <n-tabs v-model:value="uiStore.activeRightSidebarTab" type="line" animated class="right-tabs">
      <n-tab-pane name="workspace" tab="工作区">
        <div class="workspace-sidebar-content">
          <div v-if="previewLoading && !runtimeStore.workspaceFile" class="workspace-loading">
            <n-spin size="small" />
            <n-text depth="3">正在读取文件</n-text>
          </div>
          <FilePreview
            v-else-if="runtimeStore.workspaceFile"
            :file="runtimeStore.workspaceFile"
            @close="closeWorkspacePreview"
          />
          <div v-else class="workspace-browser">
            <div class="context-bar">
              <n-text depth="3">工作区：{{ workspaceContextLabel }}</n-text>
            </div>
            <WorkspaceExplorer
              class="workspace-sidebar-explorer"
              :package-id="workspacePackageId"
              @select-file="handleWorkspaceFileSelect"
            />
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="status" tab="状态">
        <div class="sidebar-content">
          <section class="status-section">
            <div class="section-title">活动</div>
            <n-empty v-if="runtimeStore.timeline.length === 0" description="暂无活动" size="small" />
            <div v-else class="timeline-list">
              <div
                v-for="item in recentTimeline"
                :key="item.id"
                class="timeline-item"
              >
                <div class="timeline-time">
                  {{ formatTime(item.timestamp) }}
                </div>
                <div class="timeline-content">
                  <strong>{{ item.nodeLabel || item.eventType }}</strong>
                  <div v-if="item.message" class="timeline-message">
                    {{ item.message }}
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section class="status-section">
            <div class="section-title">工具</div>
            <n-empty v-if="runtimeStore.tools.length === 0" description="暂无工具调用" size="small" />
            <div v-else class="tools-list">
              <div
                v-for="tool in runtimeStore.tools"
                :key="tool.activityKey"
                class="tool-item"
              >
                <n-tag :type="toolStatusType(tool.status)" size="small">
                  {{ tool.status }}
                </n-tag>
                <span class="tool-name">{{ tool.toolName }}</span>
              </div>
            </div>
          </section>

          <section class="status-section">
            <div class="section-title">计划</div>
            <n-empty v-if="!runtimeStore.currentPlan" description="暂无计划" size="small" />
            <PlanPanel v-else compact />
          </section>
        </div>
      </n-tab-pane>

      <n-tab-pane name="sessions" tab="会话">
        <AgentSessionPanel
          v-if="agentContextActive && workspacePackageId"
          :package-id="workspacePackageId"
        />
        <SessionSidebar v-else title="主会话" />
      </n-tab-pane>
    </n-tabs>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { NTabs, NTabPane, NEmpty, NTag, NSpin, NText } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import { useAgentStore } from '@/stores/agent'
import { useCommand } from '@/composables/useCommand'
import PlanPanel from '@/components/plan/PlanPanel.vue'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import FilePreview from '@/components/workspace/FilePreview.vue'
import SessionSidebar from '@/components/chat/SessionSidebar.vue'
import AgentSessionPanel from '@/components/agent/AgentSessionPanel.vue'
import type { WorkspaceEntry } from '@/types/protocol'

const route = useRoute()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const agentStore = useAgentStore()
const commands = useCommand()
const previewLoading = ref(false)

const recentTimeline = computed(() => {
  return runtimeStore.timeline.slice(-20).reverse()
})
const contextPackageId = computed(() => {
  if (agentStore.activeChatPackageId) return agentStore.activeChatPackageId
  if (route.path === '/agents' && agentStore.selectedPackageId) return agentStore.selectedPackageId
  return null
})
const contextPackage = computed(() => {
  if (!contextPackageId.value) return null
  return agentStore.agentPackages.find((pkg) => pkg.package_id === contextPackageId.value) || null
})
const agentContextActive = computed(() => Boolean(contextPackageId.value))
const workspacePackageId = computed(() => contextPackageId.value || undefined)
const workspaceContextLabel = computed(() => {
  if (!contextPackageId.value) return '闲聊'
  const pkg = contextPackage.value
  return `子 Agent · ${pkg?.agent_name || pkg?.name || '未命名 Agent'}`
})

function handleWorkspaceFileSelect(entry: WorkspaceEntry) {
  uiStore.setRightSidebarTab('workspace')
  previewLoading.value = true
  runtimeStore.workspaceFile = null
  commands.readFile(workspaceStore.currentScope, entry.path, workspacePackageId.value)
}

function closeWorkspacePreview() {
  previewLoading.value = false
  runtimeStore.workspaceFile = null
}

watch(
  () => runtimeStore.workspaceFile,
  (file) => {
    if (file) previewLoading.value = false
  }
)

watch(
  () => workspacePackageId.value,
  () => {
    closeWorkspacePreview()
  }
)

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function toolStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, any> = {
    proposed: 'default',
    approval: 'warning',
    started: 'info',
    completed: 'success',
    failed: 'error',
    observed: 'success',
  }
  return types[status] || 'default'
}
</script>

<style scoped>
.right-sidebar {
  height: 100%;
  background-color: var(--n-color);
  border-left: 1px solid var(--n-border-color);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.right-tabs {
  height: 100%;
  min-height: 0;
}

.right-sidebar :deep(.n-tabs-nav) {
  padding: 0 12px;
}

.right-sidebar :deep(.n-tabs-pane-wrapper),
.right-sidebar :deep(.n-tab-pane) {
  height: 100%;
  min-height: 0;
}

.sidebar-content {
  padding: 16px;
  overflow-y: auto;
  height: 100%;
}

.workspace-sidebar-content {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-browser {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.context-bar {
  padding: 8px 16px;
  border-bottom: 1px solid var(--n-border-color);
  background: var(--n-color);
}

.workspace-sidebar-explorer {
  flex: 1;
  min-height: 0;
}

.workspace-loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.status-section {
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--n-border-color);
}

.status-section:last-child {
  margin-bottom: 0;
  border-bottom: 0;
}

.section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.timeline-list,
.tools-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.timeline-item {
  display: flex;
  gap: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--n-border-color);
}

.timeline-time {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--n-text-color-3);
  width: 80px;
}

.timeline-content {
  flex: 1;
  font-size: 14px;
}

.timeline-message {
  margin-top: 4px;
  font-size: 13px;
  color: var(--n-text-color-2);
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 4px;
  background-color: var(--n-color-embedded);
}

.tool-name {
  font-size: 13px;
  font-family: monospace;
}
</style>
