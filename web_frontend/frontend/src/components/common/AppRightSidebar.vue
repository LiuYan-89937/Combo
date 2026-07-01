<template>
  <aside class="right-sidebar" :style="{ width: `${uiStore.rightSidebarWidth}px` }">
    <n-tabs v-model:value="uiStore.activeRightSidebarTab" type="line" animated class="right-tabs">
      <n-tab-pane name="workspace" :tab="t('right.workspace')">
        <WorkspaceSidebarPanel />
      </n-tab-pane>

      <n-tab-pane name="sessions" :tab="t('right.sessions')">
        <SessionsSidebarPanel />
      </n-tab-pane>

      <n-tab-pane name="status" :tab="t('right.status')">
        <StatusSidebarPanel />
      </n-tab-pane>

      <n-tab-pane v-if="runtimeStore.currentPlan" name="plan" :tab="t('right.plan')">
        <div class="sidebar-content">
          <PlanPanel compact />
        </div>
      </n-tab-pane>
    </n-tabs>
  </aside>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { NTabPane, NTabs } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import PlanPanel from '@/components/plan/PlanPanel.vue'
import SessionsSidebarPanel from './right-sidebar/SessionsSidebarPanel.vue'
import StatusSidebarPanel from './right-sidebar/StatusSidebarPanel.vue'
import WorkspaceSidebarPanel from './right-sidebar/WorkspaceSidebarPanel.vue'

const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const { t } = useI18n()
const allowedTabs = new Set(['workspace', 'sessions', 'status', 'plan'])

watch(
  () => uiStore.activeRightSidebarTab,
  (tab) => {
    if (!allowedTabs.has(String(tab)) || (tab === 'plan' && !runtimeStore.currentPlan)) {
      uiStore.setRightSidebarTab('workspace')
    }
  },
  { immediate: true }
)

watch(
  () => runtimeStore.currentPlan,
  (plan) => {
    if (!plan && uiStore.activeRightSidebarTab === 'plan') {
      uiStore.setRightSidebarTab('workspace')
    }
  }
)
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
</style>
