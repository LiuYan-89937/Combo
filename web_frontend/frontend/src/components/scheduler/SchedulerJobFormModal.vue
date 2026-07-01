<template>
  <n-modal v-model:show="show" preset="card" title="创建定时任务" style="width: 640px">
    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="top">
      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi label="执行方式" path="target_kind">
          <n-select v-model:value="formData.target_kind" :options="targetOptions" />
        </n-form-item-gi>

        <n-form-item-gi label="启用">
          <n-switch v-model:value="formData.enabled" />
        </n-form-item-gi>
      </n-grid>

      <n-form-item v-if="formData.target_kind === 'tool_call'" label="工具" path="tool_id">
        <n-select
          v-model:value="formData.tool_id"
          :options="toolOptions"
          filterable
          placeholder="选择工具"
        />
      </n-form-item>

      <n-form-item label="cron 表达式" path="schedule_expr">
        <n-input v-model:value="formData.schedule_expr" placeholder="0 9 * * *" />
      </n-form-item>

      <n-form-item label="任务说明" path="task_content">
        <n-input
          v-model:value="formData.task_content"
          type="textarea"
          :rows="3"
          placeholder="描述这个任务要完成什么"
        />
      </n-form-item>

      <n-form-item v-if="formData.target_kind === 'script_run'" label="脚本命令" path="command">
        <n-input
          v-model:value="formData.command"
          type="textarea"
          :rows="4"
          placeholder="输入需要定时执行的命令"
        />
      </n-form-item>

      <n-form-item v-if="formData.target_kind === 'tool_call'" label="工具参数 JSON">
        <n-input
          v-model:value="formData.arguments_json"
          type="textarea"
          :rows="5"
          placeholder="{ }"
        />
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
import { computed, ref } from 'vue'
import {
  NButton,
  NForm,
  NFormItem,
  NFormItemGi,
  NGrid,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { useSchedulerStore } from '@/stores/scheduler'
import type { SchedulerJobInput } from '@/api/commands'

type TargetKind = 'graph_run' | 'script_run' | 'tool_call'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: SchedulerJobInput]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const schedulerStore = useSchedulerStore()
const formRef = ref<FormInst | null>(null)
const formData = ref({
  target_kind: 'graph_run' as TargetKind,
  enabled: true,
  tool_id: null as string | null,
  schedule_expr: '0 9 * * *',
  task_content: '',
  command: '',
  arguments_json: '{}',
})

const targetOptions = [
  { label: '自然语言任务', value: 'graph_run' },
  { label: '脚本', value: 'script_run' },
  { label: '工具', value: 'tool_call' },
]

const toolOptions = computed(() => (
  schedulerStore.toolOptions.map((tool) => ({
    label: tool.description ? `${tool.name} - ${tool.description}` : tool.name,
    value: tool.id,
  }))
))

const rules: FormRules = {
  schedule_expr: [{ required: true, message: '请输入 cron 表达式', trigger: 'blur' }],
  task_content: [{ required: true, message: '请输入任务说明', trigger: 'blur' }],
  tool_id: [
    {
      validator: () => formData.value.target_kind !== 'tool_call' || Boolean(formData.value.tool_id),
      message: '请选择工具',
      trigger: 'change',
    },
  ],
  command: [
    {
      validator: () => formData.value.target_kind !== 'script_run' || Boolean(formData.value.command.trim()),
      message: '请输入脚本命令',
      trigger: 'blur',
    },
  ],
}

function handleSubmit() {
  formRef.value?.validate((errors) => {
    if (errors) return
    const jobInput = buildJobInput()
    if (!jobInput) return
    emit('submit', jobInput)
    resetForm()
  })
}

function buildJobInput(): SchedulerJobInput | null {
  const base = {
    task_content: formData.value.task_content.trim(),
    schedule_type: 'cron' as const,
    schedule_expr: formData.value.schedule_expr.trim(),
    enabled: formData.value.enabled,
  }

  if (formData.value.target_kind === 'script_run') {
    return {
      ...base,
      target: {
        target_type: 'script_run',
        payload: { command: formData.value.command.trim() },
      },
    }
  }

  if (formData.value.target_kind === 'tool_call') {
    const parsedArguments = parseArguments()
    if (parsedArguments === null) return null
    return {
      ...base,
      target: {
        target_type: 'tool_call',
        payload: {
          tool_id: formData.value.tool_id || '',
          arguments: parsedArguments,
        },
      },
    }
  }

  const payload: {
    message: string
    thread_policy: 'new_thread_per_run'
  } = {
    message: formData.value.task_content.trim(),
    thread_policy: 'new_thread_per_run',
  }
  return {
    ...base,
    target: {
      target_type: 'graph_run',
      payload,
    },
  }
}

function parseArguments(): Record<string, any> | null {
  const raw = formData.value.arguments_json.trim()
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

function resetForm() {
  formData.value = {
    target_kind: 'graph_run',
    enabled: true,
    tool_id: null,
    schedule_expr: '0 9 * * *',
    task_content: '',
    command: '',
    arguments_json: '{}',
  }
}
</script>
