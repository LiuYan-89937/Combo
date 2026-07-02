<template>
  <aside
    class="right-sidebar"
    :class="{ resizing: isResizing }"
    :style="{ width: `${displayedRightSidebarWidth}px` }"
  >
    <div
      class="right-sidebar-resizer"
      role="separator"
      aria-orientation="vertical"
      :aria-label="t('layout.resizeRightSidebar')"
      :title="t('layout.dragResize')"
      @pointerdown="startResize"
    ></div>

    <div class="right-sidebar-toolbar">
      <span class="right-sidebar-title">{{ t('layout.panel') }}</span>
      <n-button quaternary circle size="small" :title="t('layout.collapseRightSidebar')" @click="uiStore.toggleRightSidebar">
        <template #icon>
          <n-icon><ChevronForward /></n-icon>
        </template>
      </n-button>
    </div>

    <n-tabs v-model:value="uiStore.activeRightSidebarTab" type="line" animated class="right-tabs">
      <n-tab-pane name="workspace" :tab="t('right.workspace')">
        <WorkspaceSidebarPanel />
      </n-tab-pane>

      <n-tab-pane name="sessions" :tab="t('right.sessions')">
        <SessionsSidebarPanel />
      </n-tab-pane>

      <n-tab-pane name="status" :tab="t('right.status')">
        <StatusSidebarPanel />
      </n-tab-pane>
    </n-tabs>
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NIcon, NTabPane, NTabs } from 'naive-ui'
import { ChevronForward } from '@vicons/ionicons5'
import { useI18n } from '@/composables/useI18n'
import { RIGHT_SIDEBAR_WIDTH, useUiStore } from '@/stores/ui'
import SessionsSidebarPanel from './right-sidebar/SessionsSidebarPanel.vue'
import StatusSidebarPanel from './right-sidebar/StatusSidebarPanel.vue'
import WorkspaceSidebarPanel from './right-sidebar/WorkspaceSidebarPanel.vue'

const MAIN_CONTENT_MIN_WIDTH = 520

const uiStore = useUiStore()
const { t } = useI18n()
const allowedTabs = new Set(['workspace', 'sessions', 'status'])
const isResizing = ref(false)
const viewportWidth = ref(RIGHT_SIDEBAR_WIDTH.max + MAIN_CONTENT_MIN_WIDTH)
let resizeStartX = 0
let resizeStartWidth = RIGHT_SIDEBAR_WIDTH.default
let previousBodyCursor = ''
let previousBodyUserSelect = ''

const displayedRightSidebarWidth = computed(() => {
  return Math.min(uiStore.rightSidebarWidth, availableRightSidebarWidth())
})

watch(
  () => uiStore.activeRightSidebarTab,
  (tab) => {
    if (!allowedTabs.has(String(tab))) {
      uiStore.setRightSidebarTab('workspace')
    }
  },
  { immediate: true }
)

onMounted(() => {
  updateViewportWidth()
  window.addEventListener('resize', updateViewportWidth)
})

onBeforeUnmount(() => {
  stopResize()
  window.removeEventListener('resize', updateViewportWidth)
})

function startResize(event: PointerEvent): void {
  event.preventDefault()
  resizeStartX = event.clientX
  resizeStartWidth = displayedRightSidebarWidth.value
  isResizing.value = true
  previousBodyCursor = document.body.style.cursor
  previousBodyUserSelect = document.body.style.userSelect
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', resizeSidebar)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

function resizeSidebar(event: PointerEvent): void {
  if (!isResizing.value) return
  const delta = resizeStartX - event.clientX
  uiStore.setRightSidebarWidth(resizeStartWidth + delta, availableRightSidebarWidth())
}

function stopResize(): void {
  if (!isResizing.value) return
  isResizing.value = false
  document.body.style.cursor = previousBodyCursor
  document.body.style.userSelect = previousBodyUserSelect
  window.removeEventListener('pointermove', resizeSidebar)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
}

function updateViewportWidth(): void {
  viewportWidth.value = window.innerWidth
}

function availableRightSidebarWidth(): number {
  const occupiedWidth = uiStore.leftSidebarCollapsed ? 0 : uiStore.leftSidebarWidth
  const availableWidth = viewportWidth.value - occupiedWidth - MAIN_CONTENT_MIN_WIDTH
  return Math.max(RIGHT_SIDEBAR_WIDTH.min, availableWidth)
}
</script>

<style scoped>
.right-sidebar {
  height: 100%;
  background-color: var(--n-color);
  border-left: 1px solid var(--n-border-color);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  flex: 0 0 auto;
  position: relative;
}

.right-sidebar-resizer {
  position: absolute;
  z-index: 3;
  top: 0;
  bottom: 0;
  left: -4px;
  width: 8px;
  cursor: col-resize;
  touch-action: none;
}

.right-sidebar-resizer::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 1px;
  background: transparent;
}

.right-sidebar-resizer:hover::after,
.right-sidebar.resizing .right-sidebar-resizer::after {
  background: #111111;
}

.right-sidebar-toolbar {
  height: 40px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid var(--n-border-color);
}

.right-sidebar-title {
  color: #111111;
  font-size: 13px;
  font-weight: 600;
}

.right-tabs {
  flex: 1;
  height: auto;
  min-height: 0;
}

.right-sidebar :deep(.n-tabs-nav) {
  padding: 0 12px;
}

.right-sidebar :deep(.n-tabs-pane-wrapper),
.right-sidebar :deep(.n-tab-pane) {
  height: 100%;
  min-height: 0;
}

</style>
