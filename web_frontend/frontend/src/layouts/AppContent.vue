<template>
  <div class="app-layout">
    <!-- 全局加载条 -->
    <n-loading-bar-provider>
      <AppLoadingBar />
    </n-loading-bar-provider>

    <!-- 主应用区域 -->
    <div class="app-container">
      <!-- 顶部导航 -->
      <AppHeader />

      <!-- 主内容区 -->
      <div class="app-main">
        <n-button
          v-if="uiStore.leftSidebarCollapsed"
          class="sidebar-restore left"
          size="small"
          :title="t('layout.expandLeftSidebar')"
          :aria-label="t('layout.expandLeftSidebar')"
          @click="uiStore.toggleLeftSidebar"
        >
          <template #icon>
            <n-icon><ChevronForward /></n-icon>
          </template>
        </n-button>

        <!-- 左侧边栏 -->
        <AppSidebar v-if="!uiStore.leftSidebarCollapsed" />

        <!-- 中间内容 -->
        <main class="app-content">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </main>

        <!-- 右侧边栏 -->
        <AppRightSidebar v-if="!uiStore.rightSidebarCollapsed" />

        <n-button
          v-if="uiStore.rightSidebarCollapsed"
          class="sidebar-restore right"
          size="small"
          :title="t('layout.expandRightSidebar')"
          :aria-label="t('layout.expandRightSidebar')"
          @click="uiStore.toggleRightSidebar"
        >
          <template #icon>
            <n-icon><ChevronBack /></n-icon>
          </template>
        </n-button>
      </div>
    </div>

    <!-- 全局通知 -->
    <n-notification-provider>
      <AppNotifications />
      <SchedulerRunNotifier />
    </n-notification-provider>

    <!-- 设置抽屉 -->
    <SettingsDrawer v-model:show="uiStore.settingsDrawerOpen" />

    <!-- 调试抽屉 -->
    <DebugDrawer v-model:show="uiStore.debugDrawerOpen" />

    <!-- SSE 事件流初始化 -->
    <EventStreamManager />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NIcon } from 'naive-ui'
import { ChevronBack, ChevronForward } from '@/components/icons'
import { useUiStore } from '@/stores/ui'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import AppHeader from '@/components/common/AppHeader.vue'
import AppSidebar from '@/components/common/AppSidebar.vue'
import AppRightSidebar from '@/components/common/AppRightSidebar.vue'
import AppLoadingBar from '@/components/common/AppLoadingBar.vue'
import AppNotifications from '@/components/common/AppNotifications.vue'
import SchedulerRunNotifier from '@/components/scheduler/SchedulerRunNotifier.vue'
import SettingsDrawer from '@/components/common/SettingsDrawer.vue'
import DebugDrawer from '@/components/common/DebugDrawer.vue'
import EventStreamManager from '@/components/common/EventStreamManager.vue'

const uiStore = useUiStore()
const route = useRoute()
const { startSession } = useCommand()
const { t } = useI18n()

onMounted(() => {
  const mode = route.name === 'Manufacturing'
    ? 'create_agent'
    : route.name === 'Evolution'
      ? 'evolve_agent'
      : route.name === 'Factory'
        ? 'chat'
        : null
  startSession(true, mode)
})
</script>

<style scoped>
.app-layout {
  height: 100vh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--app-surface);
  color: var(--app-text);
}

.app-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.app-main {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
}

.app-content {
  flex: 1 1 0;
  min-width: 0;
  overflow-y: auto;
  background: var(--app-surface);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

.sidebar-restore {
  position: absolute;
  z-index: 8;
  top: 16px;
  width: 24px;
  height: 48px;
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  color: var(--app-text);
  cursor: pointer;
  box-shadow: var(--app-shadow-sm);
  transition: background-color 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
  animation: app-fade-in 0.24s ease both;
}

.sidebar-restore:active {
  transform: scale(0.95);
}

.sidebar-restore.left {
  left: 0;
  border-left: 0;
  border-radius: 0 var(--app-radius-md) var(--app-radius-md) 0;
}

.sidebar-restore.right {
  right: 0;
  border-right: 0;
  border-radius: var(--app-radius-md) 0 0 var(--app-radius-md);
}

.sidebar-restore:hover {
  background: var(--app-surface-muted);
  border-color: var(--app-border-hover);
  box-shadow: var(--app-shadow-md);
}
</style>
