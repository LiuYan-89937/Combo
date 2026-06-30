<template>
  <aside class="app-sidebar" :style="{ width: `${uiStore.leftSidebarWidth}px` }">
    <n-menu
      :value="activeKey"
      :options="menuOptions"
      @update:value="handleMenuSelect"
    />
  </aside>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NMenu, NIcon } from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import {
  ChatbubbleEllipses,
  Build,
  Rocket,
  FolderOpen,
  Library,
  Time,
  ExtensionPuzzle,
} from '@vicons/ionicons5'
import { useUiStore } from '@/stores/ui'

const router = useRouter()
const route = useRoute()
const uiStore = useUiStore()

const activeKey = computed(() => route.path)

const menuOptions = computed<MenuOption[]>(() => [
  {
    label: '闲聊',
    key: '/factory',
    icon: renderIcon(ChatbubbleEllipses),
  },
  {
    label: 'Agent 制造',
    key: '/manufacturing',
    icon: renderIcon(Build),
  },
  {
    label: '已发布 Agent',
    key: '/agents',
    icon: renderIcon(Rocket),
  },
  {
    type: 'divider',
    key: 'd1',
  },
  {
    label: '资源管理',
    key: 'resources',
    children: [
      {
        label: '工作区',
        key: '/workspace',
        icon: renderIcon(FolderOpen),
      },
      {
        label: '知识库',
        key: '/knowledge',
        icon: renderIcon(Library),
      },
      {
        label: '定时任务',
        key: '/scheduler',
        icon: renderIcon(Time),
      },
      {
        label: '扩展管理',
        key: '/extensions',
        icon: renderIcon(ExtensionPuzzle),
      },
    ],
  },
])

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

function handleMenuSelect(key: string) {
  if (key.startsWith('/')) {
    router.push(key)
  }
}
</script>

<style scoped>
.app-sidebar {
  height: 100%;
  overflow-y: auto;
  background-color: var(--n-color);
  border-right: 1px solid var(--n-border-color);
  transition: width 0.3s ease;
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
