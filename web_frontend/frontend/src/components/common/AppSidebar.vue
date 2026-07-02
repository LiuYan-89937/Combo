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
  background-color: var(--n-color);
  border-right: 1px solid var(--n-border-color);
  transition: width 0.3s ease;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-toolbar {
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid var(--n-border-color);
}

.sidebar-title {
  color: #111111;
  font-size: 13px;
  font-weight: 600;
}

.main-menu {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.app-sidebar :deep(.n-menu-item-content) {
  color: #111111;
}

.app-sidebar :deep(.n-menu-item-content .n-menu-item-content__icon),
.app-sidebar :deep(.n-menu-item-content .n-menu-item-content-header) {
  color: inherit;
}

.app-sidebar :deep(.n-menu-item-content:not(.n-menu-item-content--selected):hover) {
  background-color: #f5f5f5;
}

.app-sidebar :deep(.n-menu-item-content--selected) {
  background-color: #eeeeee;
  color: #000000;
}
</style>
