<template>
  <n-modal v-model:show="show" preset="card" title="创建定时任务" style="width: 500px">
    <n-form ref="formRef" :model="formData">
      <n-form-item label="任务内容">
        <n-input
          v-model:value="formData.task_content"
          type="textarea"
          :rows="3"
          placeholder="输入要定期执行的任务..."
        />
      </n-form-item>

      <n-form-item label="调度表达式">
        <n-input v-model:value="formData.schedule_expr" placeholder="0 9 * * *（每天 9:00）" />
      </n-form-item>

      <n-form-item label="执行模式">
        <n-select v-model:value="formData.mode" :options="modeOptions" />
      </n-form-item>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">取消</n-button>
        <n-button type="primary" @click="handleSubmit">创建</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NModal, NForm, NFormItem, NInput, NSelect, NSpace, NButton } from 'naive-ui'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: any]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const formRef = ref()
const formData = ref({
  task_content: '',
  schedule_type: 'cron',
  schedule_expr: '0 9 * * *',
  mode: 'chat',
})

const modeOptions = [
  { label: '对话模式', value: 'chat' },
  { label: '创建 Agent', value: 'create_agent' },
]

function handleSubmit() {
  const jobInput = {
    task_content: formData.value.task_content,
    schedule_type: formData.value.schedule_type,
    schedule_expr: formData.value.schedule_expr,
    target: {
      target_type: 'graph_run',
      payload: {
        message: formData.value.task_content,
        mode: formData.value.mode,
        thread_policy: 'new_thread_per_run',
      },
    },
  }
  emit('submit', jobInput)
}
</script>
