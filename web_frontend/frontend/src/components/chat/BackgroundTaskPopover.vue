<template>
  <section class="task-popover">
    <button class="task-popover-close" type="button" :aria-label="t('common.close')" @click="emit('close')">×</button>
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
  controller?: BackgroundTaskController
}>()
const emit = defineEmits<{
  close: []
  updated: [task: BackgroundTask]
  deleted: [taskId: string]
}>()
const { t } = useI18n()
</script>

<style scoped>
.task-popover { position: relative; width: min(360px, calc(100vw - 48px)); max-height: min(72vh, 680px); overflow: hidden; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-top: 0; border-radius: 0 0 var(--app-radius-lg) var(--app-radius-lg); }
.task-popover-close { position: absolute; z-index: 2; top: 12px; right: 12px; width: 26px; height: 26px; display: grid; place-items: center; padding: 0; border: 0; border-radius: 50%; color: var(--app-text); background: transparent; font-size: 17px; cursor: pointer; }
.task-popover-close:hover { background: var(--app-surface-hover); }
.task-detail { max-height: min(72vh, 680px); overflow-x: hidden; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
</style>
