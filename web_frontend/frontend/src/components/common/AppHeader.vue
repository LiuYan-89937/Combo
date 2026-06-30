<template>
  <header class="app-header">
    <div class="header-left">
      <n-button text @click="uiStore.toggleLeftSidebar">
        <n-icon size="20">
          <Menu />
        </n-icon>
      </n-button>
      <h1 class="app-title">FastAgentFactory</h1>
      <n-tag :type="connectionStatusType" size="small" round>
        {{ connectionStatusText }}
      </n-tag>
    </div>

    <div class="header-center">
      <n-breadcrumb>
        <n-breadcrumb-item>{{ currentRouteName }}</n-breadcrumb-item>
        <n-breadcrumb-item v-if="runtimeStore.currentMode">
          {{ modeLabel }}
        </n-breadcrumb-item>
      </n-breadcrumb>
    </div>

    <div class="header-right">
      <n-tag v-if="runtimeStore.runStatus !== 'idle'" :type="runStatusType" size="small" round>
        {{ runStatusText }}
      </n-tag>

      <n-button text @click="uiStore.toggleCommandPalette" title="命令面板 (Cmd+K)">
        <n-icon size="20">
          <Search />
        </n-icon>
      </n-button>

      <n-button text @click="uiStore.toggleDebugDrawer" title="调试面板">
        <n-icon size="20">
          <Bug />
        </n-icon>
      </n-button>

      <n-button text @click="uiStore.toggleSettingsDrawer" title="设置">
        <n-icon size="20">
          <Settings />
        </n-icon>
      </n-button>

      <n-button text @click="toggleTheme" title="切换主题">
        <n-icon size="20">
          <Moon v-if="uiStore.actualTheme === 'light'" />
          <Sunny v-else />
        </n-icon>
      </n-button>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon, NTag, NBreadcrumb, NBreadcrumbItem } from 'naive-ui'
import { Menu, Search, Settings, Bug, Moon, Sunny } from '@vicons/ionicons5'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'

const route = useRoute()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()

const currentRouteName = computed(() => {
  return route.meta.title || route.name || '未知页面'
})

const modeLabel = computed(() => {
  const mode = runtimeStore.currentMode
  if (!mode) return ''
  const labels = {
    chat: '对话模式',
    create_agent: '创建 Agent',
    evolve_agent: '进化 Agent',
    agent_package: 'Agent 运行',
  }
  return labels[mode as keyof typeof labels] || mode
})

const connectionStatusText = computed(() => {
  const status = runtimeStore.connectionStatus
  const labels = {
    disconnected: '未连接',
    connecting: '连接中',
    connected: '已连接',
    error: '连接错误',
  }
  return labels[status]
})

const connectionStatusType = computed(() => {
  const status = runtimeStore.connectionStatus
  const types = {
    disconnected: 'default',
    connecting: 'warning',
    connected: 'success',
    error: 'error',
  }
  return types[status] as any
})

const runStatusText = computed(() => {
  const status = runtimeStore.runStatus
  const labels = {
    idle: '空闲',
    running: '运行中',
    interrupted: '已暂停',
    completed: '已完成',
    failed: '失败',
  }
  return labels[status]
})

const runStatusType = computed(() => {
  const status = runtimeStore.runStatus
  const types = {
    idle: 'default',
    running: 'info',
    interrupted: 'warning',
    completed: 'success',
    failed: 'error',
  }
  return types[status] as any
})

function toggleTheme() {
  const current = uiStore.themeMode
  if (current === 'auto') {
    uiStore.setThemeMode('dark')
  } else if (current === 'dark') {
    uiStore.setThemeMode('light')
  } else {
    uiStore.setThemeMode('auto')
  }
}
</script>

<style scoped>
.app-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  background-color: var(--n-color);
  border-bottom: 1px solid var(--n-border-color);
  gap: 16px;
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.header-center {
  flex: 1;
  display: flex;
  justify-content: center;
  min-width: 0;
}

.app-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
}
</style>
