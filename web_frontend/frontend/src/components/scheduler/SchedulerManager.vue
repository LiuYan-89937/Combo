<template>
  <div class="scheduler-manager">
    <div class="manager-header">
      <div class="manager-title">
        <n-text strong>定时任务</n-text>
        <n-text depth="3" class="context-label">{{ schedulerContextLabel }}</n-text>
      </div>
      <n-button type="primary" @click="showCreateModal = true">
        <template #icon>
          <n-icon><Add /></n-icon>
        </template>
        创建任务
      </n-button>
    </div>

    <n-scrollbar class="job-list">
      <div class="job-grid">
        <n-card
          v-for="job in schedulerStore.jobs"
          :key="job.payload?.job_id"
          class="job-card"
        >
          <div class="job-header">
            <div class="job-info">
              <n-text strong>{{ job.title }}</n-text>
              <n-space align="center" :size="8">
                <n-tag :type="getStatusType(job.status)" size="small">
                  {{ job.status }}
                </n-tag>
                <n-tag v-if="!job.enabled" type="default" size="small">
                  已暂停
                </n-tag>
              </n-space>
            </div>
            <n-switch
              :value="job.enabled"
              @update:value="(val) => handleToggleEnabled(job, val)"
            />
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="job-schedule">
            <n-icon size="16"><Time /></n-icon>
            <n-text depth="2" style="font-size: 13px">{{ job.schedule }}</n-text>
          </div>

          <div v-if="job.targetType" class="job-target">
            <n-icon size="16"><LocateOutline /></n-icon>
            <n-text depth="2" style="font-size: 13px">{{ job.targetLabel || job.targetType }}</n-text>
          </div>

          <div class="job-actions">
            <n-button size="small" @click="handleRunNow(job)">
              立即运行
            </n-button>
            <n-button size="small" @click="handleViewHistory(job)">
              运行历史
            </n-button>
            <n-dropdown
              :options="getJobActions()"
              @select="(key) => handleAction(key, job)"
            >
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>
        </n-card>
      </div>

      <n-empty
        v-if="schedulerStore.jobs.length === 0"
        description="还没有定时任务"
        style="margin-top: 60px"
      >
        <template #extra>
          <n-button @click="showCreateModal = true">创建第一个任务</n-button>
        </template>
      </n-empty>
    </n-scrollbar>

    <!-- 创建任务弹窗 -->
    <SchedulerJobFormModal
      v-model:show="showCreateModal"
      @submit="handleCreate"
    />

    <!-- 运行历史抽屉 -->
    <SchedulerHistoryDrawer
      v-model:show="showHistoryDrawer"
      :job-id="selectedJobId"
      :package-id="resourceContext.packageId.value"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { NText, NButton, NIcon, NScrollbar, NCard, NTag, NSpace, NSwitch, NDivider, NDropdown, NEmpty, useDialog } from 'naive-ui'
import { Add, Time, LocateOutline, EllipsisHorizontal } from '@vicons/ionicons5'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import SchedulerJobFormModal from './SchedulerJobFormModal.vue'
import SchedulerHistoryDrawer from './SchedulerHistoryDrawer.vue'
import type { SchedulerJobView } from '@/types/protocol'

const schedulerStore = useSchedulerStore()
const commands = useCommand()
const dialog = useDialog()
const resourceContext = useResourceContext()
const showCreateModal = ref(false)
const showHistoryDrawer = ref(false)
const selectedJobId = ref<string | null>(null)

const schedulerContextLabel = computed(() => {
  return `当前上下文：${resourceContext.label.value}`
})

function handleToggleEnabled(job: SchedulerJobView, enabled: boolean) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  if (enabled) {
    commands.resumeJob(jobId, resourceContext.packageIdForApi.value)
  } else {
    commands.pauseJob(jobId, resourceContext.packageIdForApi.value)
  }
}

function handleRunNow(job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (jobId) {
    commands.runJobNow(jobId, resourceContext.packageIdForApi.value)
  }
}

function handleViewHistory(job: SchedulerJobView) {
  selectedJobId.value = job.payload?.job_id || null
  showHistoryDrawer.value = true
}

function handleCreate(jobData: any) {
  commands.createSchedulerJob(jobData, resourceContext.packageIdForApi.value)
  showCreateModal.value = false
}

function handleAction(key: string, job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  switch (key) {
    case 'delete':
      dialog.warning({
        title: '删除定时任务',
        content: `确定删除「${job.title}」吗？删除后不会再触发。`,
        positiveText: '删除',
        negativeText: '取消',
        positiveButtonProps: { type: 'error' },
        onPositiveClick: () => {
          commands.deleteJob(jobId, resourceContext.packageIdForApi.value)
        },
      })
      break
  }
}

function getJobActions() {
  return [
    { label: '删除', key: 'delete' },
  ]
}

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, any> = {
    ready: 'success',
    running: 'info',
    failed: 'error',
  }
  return types[status] || 'default'
}

onMounted(() => {
  commands.listAgentPackages()
  refreshCurrentScheduler()
})

watch(
  () => resourceContext.packageId.value,
  () => {
    refreshCurrentScheduler()
  }
)

function refreshCurrentScheduler() {
  const packageId = resourceContext.packageIdForApi.value
  schedulerStore.reset()
  selectedJobId.value = null
  showHistoryDrawer.value = false
  commands.refreshSchedulerOptions(packageId)
  commands.refreshScheduler(packageId)
}
</script>

<style scoped>
.scheduler-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 20px;
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.manager-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.context-label {
  font-size: 12px;
}

.job-list {
  flex: 1;
  min-height: 0;
}

.job-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.job-card {
  transition: transform 0.2s;
}

.job-card:hover {
  transform: translateY(-2px);
}

.job-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.job-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.job-schedule,
.job-target {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
}

.job-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
