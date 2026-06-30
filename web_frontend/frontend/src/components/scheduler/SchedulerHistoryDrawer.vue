<template>
  <n-drawer v-model:show="show" :width="400" placement="right">
    <n-drawer-content title="运行历史">
      <n-list bordered>
        <n-list-item v-for="run in runs" :key="run.run_id">
          <n-thing>
            <template #header>
              <n-tag :type="getRunStatusType(run.status)" size="small">
                {{ run.status }}
              </n-tag>
            </template>
            <template #description>
              <n-text depth="3" style="font-size: 12px">
                {{ formatTime(run.started_at) }}
              </n-text>
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
import { ref, computed, watch } from 'vue'
import { NDrawer, NDrawerContent, NList, NListItem, NThing, NTag, NText, NEmpty } from 'naive-ui'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'

const props = defineProps<{
  show: boolean
  jobId: string | null
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

const runs = ref<any[]>([])

watch(
  () => props.jobId,
  (jobId) => {
    if (jobId) {
      // TODO: 加载运行历史
      runs.value = []
    }
  }
)

function getRunStatusType(status: string): 'default' | 'success' | 'error' | 'info' {
  const types: Record<string, any> = {
    completed: 'success',
    failed: 'error',
    running: 'info',
  }
  return types[status] || 'default'
}

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN')
}
</script>
