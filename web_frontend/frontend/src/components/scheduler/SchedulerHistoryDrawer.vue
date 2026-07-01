<template>
  <n-drawer v-model:show="show" :width="400" placement="right">
    <n-drawer-content title="运行历史">
      <template #header-extra>
        <n-button size="small" @click="refreshRuns">刷新</n-button>
      </template>

      <n-list bordered>
        <n-list-item v-for="run in runs" :key="run.run_id">
          <n-thing>
            <template #header>
              <n-tag :type="getRunStatusType(run.status)" size="small">
                {{ run.status }}
              </n-tag>
            </template>
            <template #description>
              <div class="run-description">
                <n-text depth="3" style="font-size: 12px">
                  {{ formatTime(run.started_at || run.scheduled_at) }}
                </n-text>
                <n-text v-if="run.output_summary || run.error_summary" depth="2" style="font-size: 12px">
                  {{ run.output_summary || run.error_summary }}
                </n-text>
              </div>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="runs.length === 0"
        description="还没有运行记录"
        size="small"
        style="margin-top: 40px"
      />
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { NButton, NDrawer, NDrawerContent, NList, NListItem, NThing, NTag, NText, NEmpty } from 'naive-ui'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'

const props = defineProps<{
  show: boolean
  jobId: string | null
  packageId?: string | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const schedulerStore = useSchedulerStore()
const commands = useCommand()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const runs = computed(() => schedulerStore.runs)

watch(
  () => [props.show, props.jobId, props.packageId] as const,
  ([visible, jobId, packageId]) => {
    if (visible && jobId) {
      schedulerStore.selectJob(jobId)
      void commands.listSchedulerRuns(jobId, 50, packageId || undefined)
    }
  },
  { immediate: true }
)

function refreshRuns() {
  if (props.jobId) {
    void commands.listSchedulerRuns(props.jobId, 50, props.packageId || undefined)
  }
}

function getRunStatusType(status: string): 'default' | 'success' | 'error' | 'info' {
  const types: Record<string, any> = {
    completed: 'success',
    failed: 'error',
    running: 'info',
  }
  return types[status] || 'default'
}

function formatTime(timestamp: string): string {
  if (!timestamp) return '未开始'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN')
}
</script>

<style scoped>
.run-description {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
