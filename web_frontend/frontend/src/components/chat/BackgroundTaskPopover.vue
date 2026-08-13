<template>
  <section class="task-popover">
    <header class="task-popover-header">
      <div>
        <strong>{{ title }}</strong>
        <small v-if="subtitle">{{ subtitle }}</small>
      </div>
      <button type="button" :aria-label="t('common.close')" @click="emit('close')">×</button>
    </header>
    <div class="task-detail">
      <BackgroundTaskCard
        :task="task"
        :fallback-title="fallbackTitle"
        :controller="controller"
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
.task-popover { width: min(480px, calc(100vw - 32px)); max-height: min(72vh, 680px); overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr); color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: var(--app-radius-lg); box-shadow: 0 28px 80px color-mix(in srgb, var(--app-text) 18%, transparent); animation: task-popover-in .24s cubic-bezier(.16, 1, .3, 1) both; }
.task-popover-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--app-divider); }
.task-popover-header > div { display: flex; align-items: baseline; gap: 8px; }
.task-popover-header strong { font-size: 13px; }
.task-popover-header small { color: var(--app-text-muted); font-size: 11px; }
.task-popover-header button { width: 28px; height: 28px; border: 0; border-radius: 50%; color: var(--app-text); background: transparent; font-size: 18px; cursor: pointer; }
.task-popover-header button:hover { background: var(--app-surface-hover); }
.task-detail { overflow-y: auto; }
@keyframes task-popover-in { from { opacity: 0; transform: translateY(-7px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
</style>
