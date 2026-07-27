<template>
  <header
    class="app-header"
    :class="{ 'is-windows-desktop': isWindowsDesktop }"
    @mousedown="handleWindowDrag"
    @dblclick="handleHeaderDoubleClick"
  >
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
      <div v-if="isAgentConversation" class="agent-conversation-context">
        <span class="agent-conversation-route">
          <n-icon size="15"><PersonCircleOutline /></n-icon>
          <span>{{ currentRouteName }}</span>
        </span>
        <span class="agent-context-divider" aria-hidden="true"></span>
        <n-dropdown
          trigger="click"
          placement="bottom"
          :options="agentPackageOptions"
          @select="switchAgentPackage"
        >
          <n-button
            text
            size="small"
            class="agent-switch-trigger"
            :title="t('sidebar.switchAgent')"
            :aria-label="t('sidebar.switchAgent')"
          >
            <span class="agent-switch-label">{{ activeAgentName }}</span>
            <n-icon size="12"><CaretDown /></n-icon>
          </n-button>
        </n-dropdown>
      </div>
      <n-breadcrumb v-else>
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

      <div v-if="isWindowsDesktop" class="window-controls" aria-label="Window controls">
        <button
          class="window-control"
          type="button"
          :title="t('header.minimizeWindow')"
          :aria-label="t('header.minimizeWindow')"
          @click="minimizeDesktopWindow"
        >
          <span class="window-minimize-icon" aria-hidden="true"></span>
        </button>
        <button
          class="window-control"
          type="button"
          :title="t('header.maximizeWindow')"
          :aria-label="t('header.maximizeWindow')"
          @click="toggleMaximizeDesktopWindow"
        >
          <span class="window-maximize-icon" aria-hidden="true"></span>
        </button>
        <button
          class="window-control window-close"
          type="button"
          :title="t('header.closeWindow')"
          :aria-label="t('header.closeWindow')"
          @click="closeDesktopWindow"
        >
          <span class="window-close-icon" aria-hidden="true"></span>
        </button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { NBadge, NButton, NDropdown, NIcon, NTag, NBreadcrumb, NBreadcrumbItem } from 'naive-ui'
import { Bug, CaretDown, PersonCircleOutline, Settings, Time } from '@/components/icons'
import appIcon from '@/assets/fast-agent-factory-icon.png'
import { routeTitleKey } from '@/i18n'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { isAgentPackageRoute, isBuiltinChatRoute } from '@/utils/agentSessionRoute'
import {
  closeDesktopWindow,
  desktopPlatform,
  minimizeDesktopWindow,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
} from '@/api/desktopWindow'

const route = useRoute()
const { t } = useI18n()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const { openPackageAgentChat } = useAgentSessionNavigation()
const schedulerUnreadCount = computed(() => runtimeStore.schedulerRunNotices.filter((notice) => notice.unread).length)
const schedulerRunning = computed(() => runtimeStore.schedulerRunNotices.some((notice) => ['scheduled', 'pending', 'running'].includes(notice.status)))
const isWindowsDesktop = ref(false)

const isAgentConversation = computed(() => (
  route.name === 'Factory'
  && runtimeStore.currentMode === 'agent_package'
  && isAgentPackageRoute(route.query)
))

const activeAgentName = computed(() => {
  const pkg = agentStore.activeChatPackage
  return pkg?.agent_name
    || pkg?.name
    || pkg?.package_id
    || agentStore.activeChatPackageId
    || t('agentSessions.selectAgent')
})

const agentPackageOptions = computed(() => agentStore.agentPackages.map((pkg) => ({
  label: pkg.agent_name || pkg.name || pkg.package_id,
  key: pkg.package_id,
  disabled: pkg.package_id === agentStore.activeChatPackageId,
})))

function switchAgentPackage(packageId: string | number) {
  const normalizedPackageId = String(packageId || '').trim()
  if (!normalizedPackageId || normalizedPackageId === agentStore.activeChatPackageId) return
  void openPackageAgentChat(normalizedPackageId)
}

onMounted(async () => {
  isWindowsDesktop.value = await desktopPlatform() === 'windows'
})

function handleWindowDrag(event: MouseEvent): void {
  if (
    !isWindowsDesktop.value
    || event.button !== 0
    || (event.target as HTMLElement).closest('button, a, input, textarea, select, [role="button"], .n-dropdown')
  ) return
  void startDesktopWindowDrag()
}

function handleHeaderDoubleClick(event: MouseEvent): void {
  if (
    !isWindowsDesktop.value
    || (event.target as HTMLElement).closest('button, a, input, textarea, select, [role="button"], .n-dropdown')
  ) return
  void toggleMaximizeDesktopWindow()
}

const headerCenterStyle = computed(() => ({
  left: `${uiStore.leftSidebarCollapsed ? 0 : uiStore.leftSidebarWidth}px`,
  right: `${uiStore.rightSidebarCollapsed ? 0 : uiStore.rightSidebarWidth}px`,
}))

const currentRouteName = computed(() => {
  const isConversationRoute = route.name === 'Factory' || route.name === 'Manufacturing' || route.name === 'Evolution'
  if (route.name === 'Evolution') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'evolve_agent') return t('route.evolution')
  if (isConversationRoute && runtimeStore.currentMode === 'create_agent') return t('route.manufacturing')
  if (route.name === 'Factory' && isBuiltinChatRoute(route.query)) return t('route.chat')
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

.app-header.is-windows-desktop {
  padding-right: 0;
  user-select: none;
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

.is-windows-desktop .header-right {
  align-self: stretch;
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

.agent-conversation-context {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: min(440px, calc(100% - var(--app-space-lg) * 2));
  gap: var(--app-space-sm);
  color: var(--app-text-secondary);
  pointer-events: auto;
}

.agent-conversation-route {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  gap: 5px;
  font-size: var(--app-font-sm);
  white-space: nowrap;
}

.agent-context-divider {
  width: 1px;
  height: 14px;
  flex-shrink: 0;
  background: var(--app-divider);
}

.agent-switch-trigger {
  min-width: 0;
  max-width: 260px;
  padding: 3px 5px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text);
  font-weight: 500;
}

.agent-switch-trigger:hover {
  background: var(--app-surface-muted);
}

.agent-switch-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
  user-select: none;
  isolation: isolate;
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
  position: relative;
  padding: 2px 1px 5px;
  margin: 0;
  color: transparent;
  background:
    linear-gradient(
      112deg,
      var(--app-text-strong) 0%,
      var(--app-text-strong) 38%,
      var(--app-text-secondary) 50%,
      var(--app-text-strong) 62%,
      var(--app-text-strong) 100%
    );
  background-position: 0 50%;
  background-size: 220% 100%;
  background-clip: text;
  -webkit-background-clip: text;
  font-family: 'Avenir Next', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif;
  font-size: 17px;
  font-variation-settings: 'wght' 720;
  font-weight: 720;
  line-height: 1;
  white-space: nowrap;
  letter-spacing: -0.055em;
  transition:
    background-position var(--app-transition-slow),
    letter-spacing var(--app-transition-base);
}

.app-title::after {
  content: '';
  position: absolute;
  left: 2px;
  bottom: 0;
  width: 34px;
  height: 2px;
  border-radius: var(--app-radius-pill);
  background:
    linear-gradient(
      90deg,
      var(--app-text-strong) 0 72%,
      transparent 72% 82%,
      var(--app-text-secondary) 82% 100%
    );
  transform: skewX(-24deg);
  transform-origin: left center;
  transition: width var(--app-transition-base);
}

.brand:hover .app-title {
  background-position: 100% 50%;
  letter-spacing: -0.04em;
}

.brand:hover .app-title::after {
  width: 52px;
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

.window-controls {
  align-self: stretch;
  display: flex;
  margin-left: var(--app-space-xs);
}

.window-control {
  width: 46px;
  height: 100%;
  padding: 0;
  border: 0;
  display: grid;
  place-items: center;
  color: var(--app-text-secondary);
  background: transparent;
  cursor: default;
  transition: color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.window-control:hover {
  color: var(--app-text-strong);
  background: var(--app-surface-muted);
}

.window-control.window-close:hover {
  color: #fff;
  background: #c42b1c;
}

.window-minimize-icon,
.window-maximize-icon,
.window-close-icon {
  position: relative;
  width: 10px;
  height: 10px;
  pointer-events: none;
}

.window-minimize-icon::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 1px;
  height: 1px;
  background: currentColor;
}

.window-maximize-icon {
  box-sizing: border-box;
  border: 1px solid currentColor;
}

.window-close-icon::before,
.window-close-icon::after {
  content: '';
  position: absolute;
  top: 4.5px;
  left: -1px;
  width: 12px;
  height: 1px;
  background: currentColor;
}

.window-close-icon::before {
  transform: rotate(45deg);
}

.window-close-icon::after {
  transform: rotate(-45deg);
}

/* 中等屏隐藏 breadcrumb 只保留 tag */
@media (max-width: 768px) {
  .header-center {
    display: none;
  }
  .app-title {
    font-size: 15px;
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
