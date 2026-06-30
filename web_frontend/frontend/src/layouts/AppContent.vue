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
      </div>
    </div>

    <!-- 全局通知 -->
    <n-notification-provider>
      <AppNotifications />
    </n-notification-provider>

    <!-- 命令面板 -->
    <CommandPalette v-model:show="uiStore.commandPaletteOpen" />

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
import { useUiStore } from '@/stores/ui'
import { useCommand } from '@/composables/useCommand'
import AppHeader from '@/components/common/AppHeader.vue'
import AppSidebar from '@/components/common/AppSidebar.vue'
import AppRightSidebar from '@/components/common/AppRightSidebar.vue'
import AppLoadingBar from '@/components/common/AppLoadingBar.vue'
import AppNotifications from '@/components/common/AppNotifications.vue'
import CommandPalette from '@/components/common/CommandPalette.vue'
import SettingsDrawer from '@/components/common/SettingsDrawer.vue'
import DebugDrawer from '@/components/common/DebugDrawer.vue'
import EventStreamManager from '@/components/common/EventStreamManager.vue'

const uiStore = useUiStore()
const { startSession } = useCommand()

onMounted(() => {
  // 启动会话
  startSession(true)
})
</script>

<style scoped>
.app-layout {
  height: 100vh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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
}

.app-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
