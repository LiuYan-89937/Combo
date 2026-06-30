<template>
  <div class="scheduler-manager">
    <div class="manager-header">
      <n-text strong>定时任务</n-text>
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
            <n-text depth="2" style="font-size: 13px">{{ job.targetType }}</n-text>
          </div>

          <div class="job-actions">
            <n-button size="small" @click="handleRunNow(job)">
              立即运行
            </n-button>
            <n-button size="small" @click="handleViewHistory(job)">
              运行历史
            </n-button>
            <n-dropdown
              :options="getJobActions(job)"
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
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NText, NButton, NIcon, NScrollbar, NCard, NTag, NSpace, NSwitch, NDivider, NDropdown, NEmpty } from 'naive-ui'
import { Add, Time, LocateOutline, EllipsisHorizontal } from '@vicons/ionicons5'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'
import SchedulerJobFormModal from './SchedulerJobFormModal.vue'
import SchedulerHistoryDrawer from './SchedulerHistoryDrawer.vue'
import type { SchedulerJobView } from '@/types/protocol'

const schedulerStore = useSchedulerStore()
const commands = useCommand()
const showCreateModal = ref(false)
const showHistoryDrawer = ref(false)
const selectedJobId = ref<string | null>(null)

function handleToggleEnabled(job: SchedulerJobView, enabled: boolean) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  if (enabled) {
    commands.resumeJob(jobId)
  } else {
    commands.pauseJob(jobId)
  }
}

function handleRunNow(job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (jobId) {
    commands.runJobNow(jobId)
  }
}

function handleViewHistory(job: SchedulerJobView) {
  selectedJobId.value = job.payload?.job_id || null
  showHistoryDrawer.value = true
}

function handleCreate(jobData: any) {
  commands.createSchedulerJob(jobData)
  showCreateModal.value = false
}

function handleAction(key: string, job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  switch (key) {
    case 'delete':
      // TODO: 确认后删除
      commands.deleteJob(jobId)
      break
  }
}

function getJobActions(job: SchedulerJobView) {
  return [
    { label: '编辑', key: 'edit' },
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
  commands.refreshScheduler()
})
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
