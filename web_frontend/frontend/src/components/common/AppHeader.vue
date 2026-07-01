<template>
  <header class="app-header">
    <div class="header-left">
      <n-button text @click="uiStore.toggleLeftSidebar">
        <n-icon size="20">
          <Menu />
        </n-icon>
      </n-button>
      <h1 class="app-title">{{ t('app.name') }}</h1>
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

      <n-button text @click="uiStore.toggleDebugDrawer" :title="t('header.debugPanel')">
        <n-icon size="20">
          <Bug />
        </n-icon>
      </n-button>

      <n-button text @click="uiStore.toggleSettingsDrawer" :title="t('header.settings')">
        <n-icon size="20">
          <Settings />
        </n-icon>
      </n-button>

    </div>
  </header>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon, NTag, NBreadcrumb, NBreadcrumbItem } from 'naive-ui'
import { Menu, Settings, Bug } from '@vicons/ionicons5'
import { routeTitleKey } from '@/i18n'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useAgentStore } from '@/stores/agent'

const route = useRoute()
const { t } = useI18n()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()

const currentRouteName = computed(() => {
  const isConversationRoute = route.name === 'Factory' || route.name === 'Manufacturing' || route.name === 'Evolution'
  if (route.name === 'Evolution') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'evolve_agent') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'create_agent') return t('route.manufacturing')
  if (isConversationRoute && runtimeStore.currentMode === 'agent_package') return t('mode.agentPackageRoute')
  return t(routeTitleKey(route.name))
})

const modeLabel = computed(() => {
  const mode = runtimeStore.currentMode
  if (!mode) return ''
  if (mode === 'evolve_agent' && agentStore.selectedPackage) {
    return agentStore.selectedPackage.agent_name || agentStore.selectedPackage.name || t('common.unnamedAgent')
  }
  if (mode === 'agent_package' && agentStore.activeChatPackage) {
    return agentStore.activeChatPackage.agent_name || agentStore.activeChatPackage.name || t('common.unnamedAgent')
  }
  const labels = {
    chat: t('mode.chat'),
    create_agent: t('mode.createAgent'),
    evolve_agent: t('mode.evolveAgent'),
    agent_package: t('mode.agentPackage'),
  }
  return labels[mode as keyof typeof labels] || mode
})

const connectionStatusText = computed(() => {
  const status = runtimeStore.connectionStatus
  const labels = {
    disconnected: t('connection.disconnected'),
    connecting: t('connection.connecting'),
    connected: t('connection.connected'),
    error: t('connection.error'),
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
    idle: t('run.idle'),
    running: t('run.running'),
    interrupted: t('run.interrupted'),
    completed: t('run.completed'),
    failed: t('run.failed'),
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
