<template>
  <header
    class="app-header"
    :class="{ 'is-windows-desktop': isWindowsDesktop }"
    @mousedown="handleWindowDrag"
    @dblclick="handleHeaderDoubleClick"
  >
    <div class="header-left">
      <button class="brand" type="button" @click="openChat">
        <ComboLogo class="brand-logo" :size="30" />
        <span class="app-title">Combo</span>
      </button>
      <span
        class="connection-dot"
        :class="`is-${runtimeStore.connectionStatus}`"
        :title="connectionStatusText"
        aria-hidden="true"
      ></span>
    </div>

    <div class="header-center">
      <span v-if="isChatRoute" class="conversation-title">{{ t('route.conversation') }}</span>
      <span v-else class="conversation-title">{{ currentRouteName }}</span>
    </div>

    <div class="header-right">
      <n-button
        secondary
        circle
        size="small"
        class="library-trigger"
        data-onboarding="capability-library"
        :title="t('header.manageRuntimeResources')"
        :aria-label="t('header.manageRuntimeResources')"
        @click="capabilityLibraryOpen = true"
      >
        <template #icon><n-icon><AppsOutline /></n-icon></template>
      </n-button>
      <n-button
        text
        class="header-icon-btn"
        :title="t('header.settings')"
        :aria-label="t('header.settings')"
        @click="uiStore.toggleSettingsDrawer"
      >
        <n-icon size="19"><Settings /></n-icon>
      </n-button>

      <div v-if="isWindowsDesktop" class="window-controls" aria-label="Window controls">
        <button class="window-control" type="button" :title="t('header.minimizeWindow')" @click="minimizeDesktopWindow">
          <span class="window-minimize-icon" aria-hidden="true"></span>
        </button>
        <button class="window-control" type="button" :title="t('header.maximizeWindow')" @click="toggleMaximizeDesktopWindow">
          <span class="window-maximize-icon" aria-hidden="true"></span>
        </button>
        <button class="window-control window-close" type="button" :title="t('header.closeWindow')" @click="closeDesktopWindow">
          <span class="window-close-icon" aria-hidden="true"></span>
        </button>
      </div>
    </div>

    <CapabilityLibraryModal v-model:show="capabilityLibraryOpen" />
  </header>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watchEffect } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import { AppsOutline, Settings } from '@/components/icons'
import ComboLogo from '@/components/brand/ComboLogo.vue'
import { routeTitleKey } from '@/i18n'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useRuntimeStore } from '@/stores/runtime'
import { useCommand } from '@/composables/useCommand'
import CapabilityLibraryModal from '@/components/common/CapabilityLibraryModal.vue'
import {
  closeDesktopWindow,
  desktopPlatform,
  minimizeDesktopWindow,
  startDesktopWindowDrag,
  toggleMaximizeDesktopWindow,
} from '@/api/desktopWindow'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const agentStore = useAgentStore()
const commands = useCommand()
const isWindowsDesktop = ref(false)
const capabilityLibraryOpen = ref(false)
const isChatRoute = computed(() => route.name === 'ChatNew' || route.name === 'ChatSession')
const currentRouteName = computed(() => {
  if (isChatRoute.value) return t('route.conversation')
  return t(routeTitleKey(route.name))
})
const connectionStatusText = computed(() => ({
  disconnected: t('connection.disconnected'),
  connecting: t('connection.connecting'),
  connected: t('connection.connected'),
  reconnecting: t('connection.reconnecting'),
  error: t('connection.error'),
})[runtimeStore.connectionStatus])

function openChat() {
  void router.push({ name: 'ChatNew' })
}

onMounted(async () => {
  isWindowsDesktop.value = await desktopPlatform() === 'windows'
  if (agentStore.agentPackages.length === 0) commands.listAgentPackages()
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

watchEffect(() => {
  if (typeof document !== 'undefined') document.title = `${currentRouteName.value} - Combo`
})
</script>

<style>
.agent-switch-popout {
  width: min(310px, calc(100vw - 40px));
  max-height: min(62vh, 520px);
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--app-border);
  border-radius: 17px;
  background: var(--app-surface);
  box-shadow: 0 22px 60px color-mix(in srgb, var(--app-text) 16%, transparent);
  animation: agent-popout-right .22s cubic-bezier(.16, 1, .3, 1) both;
}
.agent-switch-popout > header { padding: 7px 9px 9px; color: var(--app-text-muted); font-size: 10px; font-weight: 650; letter-spacing: .06em; }
.agent-switch-popout > button {
  width: 100%;
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 9px;
  border: 0;
  border-radius: 11px;
  background: transparent;
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition: background .16s ease, transform .18s cubic-bezier(.16, 1, .3, 1);
}
.agent-switch-popout > button:hover { background: var(--app-surface-muted); transform: translateX(2px); }
.agent-switch-popout > button.is-active { background: var(--app-text); color: var(--app-surface); }
.agent-switch-popout > button > span:last-child { min-width: 0; display: grid; gap: 2px; }
.agent-switch-popout strong, .agent-switch-popout small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-switch-popout strong { font-size: 12px; }
.agent-switch-popout small { font-size: 9px; opacity: .6; }
.agent-target-mark { font-size: 7px; opacity: .72; }
@keyframes agent-popout-right { from { opacity: 0; transform: translateX(-10px) scale(.97); } to { opacity: 1; transform: translateX(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .agent-switch-popout { animation: none; } }
</style>

<style scoped>
.app-header {
  position: relative;
  z-index: var(--app-z-sticky);
  height: var(--app-header-height);
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto minmax(220px, 1fr);
  align-items: center;
  gap: 16px;
  padding: 0 16px;
  background: color-mix(in srgb, var(--app-surface) 96%, transparent);
  backdrop-filter: blur(18px) saturate(150%);
}
.app-header.is-windows-desktop { padding-right: 0; user-select: none; }
.header-left, .header-right { display: flex; align-items: center; min-width: 0; gap: 10px; }
.header-right { justify-content: flex-end; }
.is-windows-desktop .header-right { align-self: stretch; }
.header-center { display: flex; min-width: 0; justify-content: center; }
.brand { display: inline-flex; min-width: 0; align-items: center; gap: 8px; padding: 0; border: 0; background: none; color: var(--app-text); cursor: pointer; }
.brand-logo { transition: transform var(--app-transition-base); }
.brand:hover .brand-logo { transform: rotate(-4deg) scale(1.06); }
.app-title { font-family: 'Avenir Next', 'SF Pro Display', sans-serif; font-size: 15px; font-weight: 730; letter-spacing: -.045em; }
.connection-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--app-text-subtle); transition: background .2s ease, transform .2s ease; }
.connection-dot.is-connected { background: var(--app-success); }
.connection-dot.is-connecting { background: var(--app-warning); animation: connection-breathe 1.4s ease-in-out infinite; }
.connection-dot.is-error { background: var(--app-error); }
.conversation-title { max-width: 420px; overflow: hidden; color: var(--app-text); font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
button.conversation-title { display: flex; align-items: center; gap: 6px; padding: 6px 10px; border: 0; border-radius: 999px; background: transparent; cursor: pointer; }
button.conversation-title:hover { background: var(--app-surface-muted); }
.library-trigger { border-radius: 999px; padding: 0; }
.header-icon-btn { width: 32px; height: 32px; border-radius: 50%; }
.window-controls { align-self: stretch; display: flex; margin-left: 4px; }
.window-control { width: 46px; border: 0; background: transparent; color: var(--app-text); cursor: default; }
.window-control:hover { background: var(--app-surface-muted); }
.window-control.window-close:hover { background: var(--app-text); color: var(--app-surface); }
.window-minimize-icon, .window-maximize-icon, .window-close-icon { position: relative; display: block; width: 10px; height: 10px; margin: auto; }
.window-minimize-icon::before { position: absolute; inset: 5px 0 auto; height: 1px; background: currentColor; content: ''; }
.window-maximize-icon { border: 1px solid currentColor; }
.window-close-icon::before, .window-close-icon::after { position: absolute; left: 5px; width: 1px; height: 12px; background: currentColor; content: ''; }
.window-close-icon::before { transform: rotate(45deg); }
.window-close-icon::after { transform: rotate(-45deg); }
@keyframes connection-breathe { 50% { transform: scale(1.5); opacity: .55; } }
@media (max-width: 760px) { .app-header { grid-template-columns: auto 1fr auto; } .app-title { display: none; } .library-trigger :deep(.n-button__content) { font-size: 0; } }
</style>
