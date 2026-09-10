<template>
  <n-drawer v-model:show="show" :width="420" placement="right" @after-enter="markAllRead">
    <n-drawer-content>
      <template #header>
        <div class="drawer-header">
          <span>{{ t('scheduler.activityTitle') }}</span>
          <n-button size="small" @click="openSchedulerPage">{{ t('scheduler.manageTasks') }}</n-button>
        </div>
      </template>

      <div v-if="notices.length" class="notice-list">
        <BackgroundTaskCard
          v-for="notice in notices"
          :key="notice.id"
          :task="noticeTask(notice)"
          :fallback-title="t('scheduler.title')"
          :controller="schedulerTaskController"
          @deleted="markNoticeDismissed"
        />
      </div>
      <n-empty v-else :description="t('scheduler.noRecentActivity')" class="empty-state" />
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NDrawer, NDrawerContent, NEmpty } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import BackgroundTaskCard, { type BackgroundTaskController } from '@/components/chat/BackgroundTaskCard.vue'
import type { BackgroundTask, BackgroundTaskEvent, BackgroundTaskStatus, InteractionAction } from '@/api/backgroundTasks'
import type { SchedulerRunNoticeView } from '@/types/protocol'
import { schedulerApi } from '@/api/scheduler'
import { schedulerActivity } from './schedulerActivity'

const router = useRouter()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const { t } = useI18n()

const show = computed({
  get: () => uiStore.schedulerActivityDrawerOpen,
  set: (value: boolean) => {
    if (!value) uiStore.closeSchedulerActivityDrawer()
  },
})
const dismissedNoticeIds = ref(new Set<string>())
const notices = computed(() => runtimeStore.schedulerRunNotices.filter(
  notice => !dismissedNoticeIds.value.has(notice.id),
))

const schedulerTaskController: BackgroundTaskController = {
  events: async (runId, after) => {
    const response = await schedulerApi.runEvents(runId, after)
    return {
      events: response.events.flatMap((event): BackgroundTaskEvent[] => {
        const activity = schedulerActivity(event, key => t(key as any))
        return activity ? [{
          seq: event.sequence,
          event_id: `${event.run_id}:${event.sequence}`,
          event_type: 'background_task_activity',
          created_at: event.created_at,
          task_id: event.run_id,
          payload: activity,
        }] : []
      }),
    }
  },
  cancel: async current => {
    const response = await schedulerApi.cancelRun(current.task_id)
    return { ...current, ...noticeTaskFromRun(response.run as Record<string, unknown>) }
  },
  delete: async () => true,
  resolveInteraction: async (current, interactionId, action, payload) => {
    const decision = schedulerDecision(action)
    await schedulerApi.resolveInteraction(current.task_id, interactionId, decision, String(payload.answer || ''))
    return { ...current, pending_interaction: null }
  },
}

function schedulerDecision(action: InteractionAction): 'approve' | 'reject' | 'trust' | 'answer' | 'revise' {
  if (action === 'deny') return 'reject'
  if (action === 'trust_tool') return 'trust'
  if (action === 'continue') return 'approve'
  return action
}

function markAllRead() {
  notices.value.forEach((notice) => runtimeStore.markSchedulerNoticeRead(notice.id))
}

function openSchedulerPage() {
  uiStore.closeSchedulerActivityDrawer()
  void router.push('/scheduler')
}

function noticeTask(notice: SchedulerRunNoticeView): BackgroundTask {
  const status = noticeStatus(notice.status)
  return {
    task_id: notice.runId || notice.id,
    session_id: notice.sessionId || '',
    type: 'sub_agent',
    status,
    request_id: notice.requestId || notice.runId || notice.id,
    child_runtime_instance_id: '',
    agent_name: notice.title,
    task_text: notice.title,
    activity_summary: notice.summary,
    activity_updated_at: notice.timestamp,
    payload: notice.payload || {},
    delivery_standard: {},
    visible_context: {},
    depends_on: [],
    input_artifacts: [],
    artifact_refs: [],
    result_summary: status === 'succeeded' ? notice.summary : '',
    result: recordValue(notice.payload.result),
    error: status === 'failed' ? { message: notice.summary, details: notice.payload } : null,
    pending_interaction: null,
    created_at: notice.timestamp,
    updated_at: notice.timestamp,
    started_at: notice.timestamp,
    completed_at: ['succeeded', 'failed', 'cancelled'].includes(status) ? notice.timestamp : null,
    revision: 0,
  }
}

function noticeTaskFromRun(run: Record<string, unknown>): Partial<BackgroundTask> {
  const status = noticeStatus(String(run.status || 'running'))
  return {
    status,
    result_summary: String(run.result_summary || ''),
    result: recordValue(run.result),
    error: recordValue(run.error) as BackgroundTask['error'],
    completed_at: String(run.completed_at || '') || null,
  }
}

function noticeStatus(status: string): BackgroundTaskStatus {
  if (status === 'completed' || status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  if (status === 'waiting_approval' || status === 'waiting_external') return status
  return 'running'
}

function recordValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : null
}

function markNoticeDismissed(id: string) {
  dismissedNoticeIds.value = new Set([...dismissedNoticeIds.value, id])
  runtimeStore.markSchedulerNoticeRead(id)
}
</script>

<style scoped>
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  gap: var(--app-space-sm);
}

.notice-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.notice-list :deep(.background-task-card) {
  margin: 0;
}

.empty-state {
  margin-top: 72px;
}
</style>
