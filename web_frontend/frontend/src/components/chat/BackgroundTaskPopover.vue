<template>
  <section class="task-popover" :class="{ 'task-popover-wide': wide, 'task-popover-detached': detached }">
    <button class="task-popover-close" type="button" :aria-label="t('backgroundTask.closeCapsule')" @click="emit('dismiss')">×</button>
    <div class="task-detail">
      <BackgroundTaskCard
        :task="task"
        :fallback-title="fallbackTitle"
        :controller="controller"
        compact-header
        @updated="emit('updated', $event)"
        @deleted="emit('deleted', $event)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import type { BackgroundTask } from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskCard, { type BackgroundTaskController } from './BackgroundTaskCard.vue'

defineProps<{
  task: BackgroundTask
  title: string
  subtitle?: string
  fallbackTitle?: string
  wide?: boolean
  /** Render as a standalone floating card instead of merging with its capsule. */
  detached?: boolean
  controller?: BackgroundTaskController
}>()
const emit = defineEmits<{
  dismiss: []
  updated: [task: BackgroundTask]
  deleted: [taskId: string]
}>()
const { t } = useI18n()
</script>

<style scoped>
.task-popover { position: relative; width: min(360px, calc(100vw - 48px)); max-height: min(72vh, 680px); overflow: hidden; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-top: 0; border-radius: 0 0 var(--app-radius-lg) var(--app-radius-lg); }
.task-popover-wide { width: min(460px, calc(100vw - 20px)); }
/* Detached variant: an independent rounded card sitting one gap below its capsule,
   mirroring the browser / computer-use floating panels instead of merging into one
   card with square corners at the junction. */
.task-popover-detached { margin-top: var(--app-space-xs); border-top: 1px solid var(--app-border); border-radius: var(--app-radius-lg); box-shadow: var(--app-shadow-lg); }
.task-popover-close { position: absolute; z-index: 2; top: 12px; right: 12px; width: 26px; height: 26px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 50%; color: var(--app-text); background: transparent; font-size: 17px; cursor: pointer; }
.task-popover-close:hover { background: var(--app-surface-hover); }
.task-detail { max-height: min(72vh, 680px); overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
</style>
