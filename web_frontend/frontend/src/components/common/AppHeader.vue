<template>
  <header class="app-header">
    <div class="header-left">
      <div class="brand">
        <img
          :src="appIcon"
          class="brand-logo"
          alt="FastAgentFactory"
          width="32"
          height="32"
          decoding="async"
        />
        <h1 class="app-title">{{ t('app.name') }}</h1>
      </div>
      <n-tag
        :type="connectionStatusType"
        size="small"
        round
        class="connection-tag"
        :class="{
          'is-connected': runtimeStore.connectionStatus === 'connected',
          'is-connecting': runtimeStore.connectionStatus === 'connecting',
        }"
      >
        <template #icon>
          <span class="connection-dot" aria-hidden="true"></span>
        </template>
        {{ connectionStatusText }}
      </n-tag>
    </div>

    <div class="header-center" :style="headerCenterStyle">
      <n-breadcrumb>
        <n-breadcrumb-item>{{ currentRouteName }}</n-breadcrumb-item>
      </n-breadcrumb>
    </div>

    <div class="header-right">
      <n-tag
        v-if="runtimeStore.runStatus !== 'idle'"
        :type="runStatusType"
        size="small"
        round
        class="run-status-tag"
        :class="{ 'is-running': runtimeStore.runStatus === 'running' }"
      >
        {{ runStatusText }}
      </n-tag>

      <n-badge
        :value="schedulerUnreadCount || undefined"
        :show="schedulerUnreadCount > 0 || schedulerRunning"
        :dot="schedulerUnreadCount === 0 && schedulerRunning"
      >
        <n-button
          text
          class="header-icon-btn"
          :class="{ 'is-active': schedulerRunning }"
          :title="t('scheduler.activityTitle')"
          :aria-label="t('scheduler.activityTitle')"
          @click="uiStore.openSchedulerActivityDrawer"
        >
          <n-icon size="20"><Time /></n-icon>
        </n-button>
      </n-badge>

      <n-button
        text
        class="header-icon-btn"
        :title="t('header.debugPanel')"
        :aria-label="t('header.debugPanel')"
        @click="uiStore.toggleDebugDrawer"
      >
        <n-icon size="20">
          <Bug />
        </n-icon>
      </n-button>

      <n-button
        text
        class="header-icon-btn"
        :title="t('header.settings')"
        :aria-label="t('header.settings')"
        @click="uiStore.toggleSettingsDrawer"
      >
        <n-icon size="20">
          <Settings />
        </n-icon>
      </n-button>

    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { NBadge, NButton, NIcon, NTag, NBreadcrumb, NBreadcrumbItem } from 'naive-ui'
import { Bug, Settings, Time } from '@/components/icons'
import appIcon from '@/assets/fast-agent-factory-icon.png'
import { routeTitleKey } from '@/i18n'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'

const route = useRoute()
const { t } = useI18n()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const schedulerUnreadCount = computed(() => runtimeStore.schedulerRunNotices.filter((notice) => notice.unread).length)
const schedulerRunning = computed(() => runtimeStore.schedulerRunNotices.some((notice) => ['scheduled', 'pending', 'running'].includes(notice.status)))

const headerCenterStyle = computed(() => ({
  left: `${uiStore.leftSidebarCollapsed ? 0 : uiStore.leftSidebarWidth}px`,
  right: `${uiStore.rightSidebarCollapsed ? 0 : uiStore.rightSidebarWidth}px`,
}))

const currentRouteName = computed(() => {
  const isConversationRoute = route.name === 'Factory' || route.name === 'Manufacturing' || route.name === 'Evolution'
  if (route.name === 'Evolution') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'evolve_agent') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'create_agent') return t('route.manufacturing')
  if (isConversationRoute && runtimeStore.currentMode === 'agent_package') return t('mode.agentPackageRoute')
  return t(routeTitleKey(route.name))
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
    stopped: t('run.stopped'),
    cancelled: t('run.cancelled'),
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
    stopped: 'default',
    cancelled: 'default',
    failed: 'error',
  }
  return types[status] as any
})

watchEffect(() => {
  if (typeof document !== 'undefined') {
    document.title = `${currentRouteName.value} - FastAgentFactory`
  }
})
</script>

<style scoped>
.app-header {
  height: var(--app-header-height);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--app-space-lg);
  background: var(--app-glass-background);
  border-bottom: 1px solid var(--app-divider);
  gap: var(--app-space-lg);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  position: relative;
  z-index: var(--app-z-sticky);
  transition: background var(--app-transition-base);
}

/* 不支持 backdrop-filter 时降级 */
@supports not (backdrop-filter: blur(1px)) {
  .app-header {
    background: var(--app-surface);
  }
}

.header-left,
.header-right {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  min-width: 0;
}

.header-right {
  gap: var(--app-space-sm);
}

.header-center {
  position: absolute;
  top: 0;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  pointer-events: none;
}

.header-center :deep(.n-breadcrumb) {
  pointer-events: auto;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
  user-select: none;
}

.brand-logo {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  object-fit: contain;
  transition: transform var(--app-transition-base), filter var(--app-transition-base);
}

.brand-logo:hover {
  transform: scale(1.05) rotate(-2deg);
}

/* 图标是黑色形状 + 透明背景。
 * 浅色模式：原样显示。
 * 暗色模式：invert 把黑色形状反转成白色，透明部分保持透明。
 */
:root[data-theme='dark'] .brand-logo {
  filter: invert(1);
}

.app-title {
  font-size: var(--app-font-xl);
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
  letter-spacing: -0.01em;
  color: var(--app-text-strong);
}

.connection-tag {
  transition: background-color var(--app-transition-base), border-color var(--app-transition-base);
}

.connection-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  vertical-align: middle;
}

.connection-tag.is-connecting .connection-dot {
  animation: app-pulse-soft 1.2s ease-in-out infinite;
}

.connection-tag.is-connected .connection-dot {
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 24%, transparent);
}

.run-status-tag.is-running {
  position: relative;
}

.run-status-tag.is-running::after {
  content: '';
  position: absolute;
  inset: -2px;
  border-radius: inherit;
  border: 1px solid currentColor;
  opacity: 0.4;
  animation: run-status-halo 1.6s ease-in-out infinite;
  pointer-events: none;
}

@keyframes run-status-halo {
  0%, 100% { transform: scale(1); opacity: 0.4; }
  50% { transform: scale(1.08); opacity: 0; }
}

.header-icon-btn {
  transition: transform var(--app-transition-fast), background-color var(--app-transition-fast);
  border-radius: var(--app-radius-md);
  padding: 6px;
}

.header-icon-btn.is-active {
  color: var(--app-info);
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

.header-icon-btn:hover {
  background: var(--app-surface-muted);
}

.header-icon-btn:active {
  transform: scale(0.92);
}

/* 中等屏隐藏 breadcrumb 只保留 tag */
@media (max-width: 768px) {
  .header-center {
    display: none;
  }
  .app-title {
    font-size: var(--app-font-lg);
  }
  .brand-logo {
    width: 24px;
    height: 24px;
  }
}

@media (max-width: 480px) {
  .app-title {
    display: none;
  }
}
</style>
