<template>
  <aside class="app-sidebar" :style="{ width: `${uiStore.leftSidebarWidth}px` }">
    <div class="sidebar-toolbar">
      <span class="sidebar-title">{{ t('layout.navigation') }}</span>
      <n-button quaternary circle size="small" :title="t('layout.collapseLeftSidebar')" @click="uiStore.toggleLeftSidebar">
        <template #icon>
          <n-icon><ChevronBack /></n-icon>
        </template>
      </n-button>
    </div>

    <n-menu
      class="main-menu"
      :value="activeKey"
      :options="menuOptions"
      @update:value="handleMenuSelect"
    />

    <RecentAgentPanel />
  </aside>
</template>

<script setup lang="ts">
import { NButton, NIcon, NMenu } from 'naive-ui'
import { ChevronBack } from '@vicons/ionicons5'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import RecentAgentPanel from './sidebar/RecentAgentPanel.vue'
import { useSidebarNavigation } from './sidebar/useSidebarNavigation'

const uiStore = useUiStore()
const { t } = useI18n()
const { activeKey, handleMenuSelect, menuOptions } = useSidebarNavigation()
</script>

<style scoped>
.app-sidebar {
  height: 100%;
  background-color: var(--app-surface);
  border-right: 1px solid var(--app-border);
  transition: width var(--app-transition-slow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.sidebar-toolbar {
  height: var(--app-toolbar-height);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  padding: 0 var(--app-space-sm) 0 var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.sidebar-title {
  color: var(--app-text);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.main-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 8px;
}

.app-sidebar :deep(.n-menu-item-content) {
  color: var(--app-text);
  border-radius: 6px;
  transition: background-color 0.15s ease, color 0.15s ease;
}

.app-sidebar :deep(.n-menu-item-content .n-menu-item-content__icon),
.app-sidebar :deep(.n-menu-item-content .n-menu-item-content-header) {
  color: inherit;
}

.app-sidebar :deep(.n-menu-item-content:not(.n-menu-item-content--selected):hover) {
  background-color: var(--app-surface-muted);
}

.app-sidebar :deep(.n-menu-item-content--selected) {
  background-color: var(--app-surface-pressed);
  color: var(--app-text-strong);
  font-weight: 500;
}
</style>
