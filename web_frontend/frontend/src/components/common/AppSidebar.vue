<template>
  <aside class="app-sidebar" :style="{ width: `${uiStore.leftSidebarWidth}px` }">
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
import { NMenu } from 'naive-ui'
import { useUiStore } from '@/stores/ui'
import RecentAgentPanel from './sidebar/RecentAgentPanel.vue'
import { useSidebarNavigation } from './sidebar/useSidebarNavigation'

const uiStore = useUiStore()
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
