<template>
  <span aria-hidden="true" />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import type { SchedulerRunNoticeView } from '@/types/protocol'

const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const { t } = useI18n()
const notifiedNoticeKeys = new Set(
  runtimeStore.schedulerRunNotices
    .filter(isTerminalNotice)
    .map(noticeKey)
)

watch(
  () => runtimeStore.schedulerRunNotices.map((notice) => `${notice.id}:${notice.status}`).join('|'),
  () => {
    runtimeStore.schedulerRunNotices
      .filter(isTerminalNotice)
      .forEach((notice) => {
        const key = noticeKey(notice)
        if (notifiedNoticeKeys.has(key)) return
        notifiedNoticeKeys.add(key)
        uiStore.addNotification({
          type: notificationType(notice.status),
          title: notificationTitle(notice),
          message: notice.summary,
          duration: notificationDuration(notice.status),
          actionLabel: t('scheduler.viewDetails'),
          onAction: () => uiStore.openSchedulerActivityDrawer(),
        })
      })
  },
)

function noticeKey(notice: SchedulerRunNoticeView): string {
  return `${notice.id}:${notice.status}`
}

function isTerminalNotice(notice: SchedulerRunNoticeView): boolean {
  return ['completed', 'failed', 'skipped', 'cancelled'].includes(notice.status)
}

function notificationType(status: string): 'success' | 'warning' | 'error' {
  if (status === 'completed') return 'success'
  if (status === 'skipped') return 'warning'
  return 'error'
}

function notificationTitle(notice: SchedulerRunNoticeView): string {
  return `${noticeTitle(notice)} · ${statusLabel(notice.status)}`
}

function noticeTitle(notice: SchedulerRunNoticeView): string {
  if (notice.targetType === 'script_run') return t('scheduler.noticeScript')
  if (notice.targetType === 'tool_call') return t('scheduler.noticeTool')
  if (notice.targetScope === 'agent_package' || notice.packageId) {
    return notice.packageName
      ? t('scheduler.noticeAgentNamed', { name: notice.packageName })
      : t('scheduler.noticeAgent')
  }
  return t('scheduler.noticeChat')
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: t('scheduler.status.completed'),
    failed: t('scheduler.status.failed'),
    skipped: t('scheduler.status.skipped'),
    cancelled: t('scheduler.status.cancelled'),
  }
  return labels[status] || t('scheduler.status.updated')
}

function notificationDuration(status: string): number {
  return status === 'completed' ? 8000 : 10000
}
</script>
