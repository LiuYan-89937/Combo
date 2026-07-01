/**
 * UI 状态 Store
 * 管理全局 UI 状态（主题、侧边栏、弹窗等）
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
  detectBrowserLocale,
  normalizeLocale,
  type Locale,
} from '@/i18n'

export type ThemeMode = 'light' | 'dark' | 'auto'
export type RightSidebarTab = 'workspace' | 'status' | 'sessions' | 'plan'

const STORAGE_KEYS = {
  locale: 'fast-agent-factory.locale',
} as const

function readStoredLocale(): Locale {
  if (typeof window === 'undefined') return 'zh-CN'
  const stored = window.localStorage.getItem(STORAGE_KEYS.locale)
  return stored ? normalizeLocale(stored) : detectBrowserLocale()
}

function writeStorage(key: string, value: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(key, value)
}

export const useUiStore = defineStore('ui', () => {
  // ========== 主题 ==========
  const themeMode = ref<ThemeMode>('light')
  const isDarkMode = ref(false)
  const locale = ref<Locale>(readStoredLocale())

  // ========== 布局 ==========
  const leftSidebarCollapsed = ref(false)
  const rightSidebarCollapsed = ref(false)
  const leftSidebarWidth = ref(280)
  const rightSidebarWidth = ref(320)
  const activeRightSidebarTab = ref<RightSidebarTab>('workspace')

  // ========== 弹窗/抽屉 ==========
  const settingsDrawerOpen = ref(false)
  const debugDrawerOpen = ref(false)

  // ========== 通知 ==========
  interface Notification {
    id: string
    type: 'info' | 'success' | 'warning' | 'error'
    title: string
    message?: string
    duration?: number
    actionLabel?: string
    onAction?: () => void
  }

  const notifications = ref<Notification[]>([])

  function addNotification(notification: Omit<Notification, 'id'>): string {
    const id = `notif-${Date.now()}-${Math.random().toString(36).slice(2)}`
    notifications.value.push({ id, ...notification })

    // 自动移除
    if (notification.duration !== 0) {
      setTimeout(() => {
        removeNotification(id)
      }, notification.duration || 5000)
    }

    return id
  }

  function removeNotification(id: string): void {
    const index = notifications.value.findIndex((n) => n.id === id)
    if (index !== -1) {
      notifications.value.splice(index, 1)
    }
  }

  // ========== 加载状态 ==========
  const globalLoading = ref(false)
  const loadingTasks = ref<Set<string>>(new Set())

  function startLoading(taskId?: string): string {
    const id = taskId || `task-${Date.now()}-${Math.random().toString(36).slice(2)}`
    loadingTasks.value.add(id)
    globalLoading.value = true
    return id
  }

  function stopLoading(taskId: string): void {
    loadingTasks.value.delete(taskId)
    if (loadingTasks.value.size === 0) {
      globalLoading.value = false
    }
  }

  // ========== 计算属性 ==========
  const actualTheme = computed(() => {
    if (themeMode.value === 'auto') {
      return isDarkMode.value ? 'dark' : 'light'
    }
    return themeMode.value
  })

  // ========== Actions ==========
  function toggleLeftSidebar(): void {
    leftSidebarCollapsed.value = !leftSidebarCollapsed.value
  }

  function toggleRightSidebar(): void {
    rightSidebarCollapsed.value = !rightSidebarCollapsed.value
  }

  function openRightSidebar(tab: RightSidebarTab = activeRightSidebarTab.value): void {
    rightSidebarCollapsed.value = false
    activeRightSidebarTab.value = tab
  }

  function setRightSidebarTab(tab: RightSidebarTab): void {
    activeRightSidebarTab.value = tab
  }

  function setThemeMode(mode: ThemeMode): void {
    themeMode.value = mode
    if (mode !== 'auto') {
      isDarkMode.value = mode === 'dark'
    }
  }

  function setLocale(nextLocale: Locale): void {
    locale.value = nextLocale
    writeStorage(STORAGE_KEYS.locale, nextLocale)
  }

  function toggleSettingsDrawer(): void {
    settingsDrawerOpen.value = !settingsDrawerOpen.value
  }

  function toggleDebugDrawer(): void {
    debugDrawerOpen.value = !debugDrawerOpen.value
  }

  // 初始化主题监听
  if (typeof window !== 'undefined') {
    watch(
      locale,
      (value) => {
        document.documentElement.lang = value
      },
      { immediate: true }
    )
  }

  return {
    // State
    themeMode,
    isDarkMode,
    locale,
    leftSidebarCollapsed,
    rightSidebarCollapsed,
    leftSidebarWidth,
    rightSidebarWidth,
    activeRightSidebarTab,
    settingsDrawerOpen,
    debugDrawerOpen,
    notifications,
    globalLoading,
    loadingTasks,

    // Computed
    actualTheme,

    // Actions
    toggleLeftSidebar,
    toggleRightSidebar,
    openRightSidebar,
    setRightSidebarTab,
    setThemeMode,
    setLocale,
    toggleSettingsDrawer,
    toggleDebugDrawer,
    addNotification,
    removeNotification,
    startLoading,
    stopLoading,
  }
})
