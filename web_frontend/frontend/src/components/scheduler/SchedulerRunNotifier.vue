<template>
  <span aria-hidden="true" />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useSchedulerNoticeNavigation } from '@/composables/useSchedulerNoticeNavigation'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import type { SchedulerRunNoticeView } from '@/types/protocol'

const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const { canOpenSchedulerNoticeConversation, openSchedulerNoticeConversation } = useSchedulerNoticeNavigation()
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
          actionLabel: canOpenSchedulerNoticeConversation(notice) ? '查看会话' : undefined,
          onAction: canOpenSchedulerNoticeConversation(notice)
            ? () => {
                openSchedulerNoticeConversation(notice)
              }
            : undefined,
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
  return `${notice.title} · ${statusLabel(notice.status)}`
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: '已完成',
    failed: '失败',
    skipped: '跳过',
    cancelled: '取消',
  }
  return labels[status] || '更新'
}

function notificationDuration(status: string): number {
  return status === 'completed' ? 8000 : 10000
}
</script>
