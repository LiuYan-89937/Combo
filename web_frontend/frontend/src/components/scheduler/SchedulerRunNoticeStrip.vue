<template>
  <div v-if="displayedNotices.length > 0" class="scheduler-run-notices">
    <button
      v-for="notice in displayedNotices"
      :key="notice.id"
      class="scheduler-run-notice"
      :class="{ unread: notice.unread }"
      type="button"
      @click="$emit('open', notice)"
    >
      <span class="notice-icon" aria-hidden="true">
        <n-icon size="16"><Time /></n-icon>
      </span>
      <span class="notice-main">
        <span class="notice-title">{{ notice.title }}</span>
        <span class="notice-summary">{{ notice.summary }}</span>
      </span>
      <n-tag size="small" :bordered="false" :type="statusType(notice.status)">
        {{ statusLabel(notice.status) }}
      </n-tag>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon, NTag } from 'naive-ui'
import { Time } from '@vicons/ionicons5'
import type { SchedulerRunNoticeView } from '@/types/protocol'

const props = defineProps<{
  notices: SchedulerRunNoticeView[]
}>()

defineEmits<{
  open: [notice: SchedulerRunNoticeView]
}>()

const displayedNotices = computed(() => (
  props.notices
    .filter((notice) => notice.status !== 'scheduled')
    .slice(0, 4)
))

function statusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  if (status === 'completed') return 'success'
  if (status === 'failed' || status === 'cancelled') return 'error'
  if (status === 'running') return 'info'
  if (status === 'skipped') return 'warning'
  return 'default'
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    skipped: '跳过',
    cancelled: '取消',
  }
  return labels[status] || status || '更新'
}
</script>

<style scoped>
.scheduler-run-notices {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0 16px 12px;
}

.scheduler-run-notice {
  width: 100%;
  min-height: 48px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  background: var(--n-color);
  color: var(--n-text-color);
  text-align: left;
  cursor: pointer;
}

.scheduler-run-notice:hover {
  border-color: var(--n-text-color-3);
  background: var(--n-color-hover);
}

.scheduler-run-notice.unread {
  border-color: var(--n-text-color-2);
}

.notice-icon {
  display: inline-flex;
  color: var(--n-text-color-2);
}

.notice-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.notice-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notice-summary {
  font-size: 12px;
  color: var(--n-text-color-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
