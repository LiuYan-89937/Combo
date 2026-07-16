<template>
  <n-modal v-model:show="show" preset="card" :title="t('scheduler.createTitle')" style="width: 640px">
    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="top">
      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi :label="t('scheduler.targetKind')" path="target_kind">
          <n-select v-model:value="formData.target_kind" :options="targetOptions" />
        </n-form-item-gi>

        <n-form-item-gi :label="t('scheduler.enabled')">
          <n-switch v-model:value="formData.enabled" />
        </n-form-item-gi>
      </n-grid>

      <n-form-item v-if="formData.target_kind === 'tool_call'" :label="t('scheduler.tool')" path="tool_id">
        <n-select
          v-model:value="formData.tool_id"
          :options="toolOptions"
          filterable
          :placeholder="t('scheduler.toolPlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('scheduler.cron')" path="schedule_expr">
        <n-input v-model:value="formData.schedule_expr" placeholder="0 9 * * *" />
      </n-form-item>

      <n-form-item :label="t('scheduler.task')" path="task_content">
        <n-input
          v-model:value="formData.task_content"
          type="textarea"
          :rows="3"
          :placeholder="t('scheduler.taskPlaceholder')"
        />
      </n-form-item>

      <n-form-item v-if="formData.target_kind === 'script_run'" :label="t('scheduler.scriptCommand')" path="command">
        <n-input
          v-model:value="formData.command"
          type="textarea"
          :rows="4"
          :placeholder="t('scheduler.scriptCommandPlaceholder')"
        />
      </n-form-item>

      <n-form-item v-if="formData.target_kind === 'tool_call'" :label="t('scheduler.toolArguments')">
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
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" @click="handleSubmit">{{ t('scheduler.create') }}</n-button>
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
import type { SchedulerJobInput } from '@/api/resourceTypes'
import { useI18n } from '@/composables/useI18n'

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
const { t } = useI18n()
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

const targetOptions = computed(() => [
  { label: t('scheduler.targetGraph'), value: 'graph_run' },
  { label: t('scheduler.targetScript'), value: 'script_run' },
  { label: t('scheduler.targetTool'), value: 'tool_call' },
])

const toolOptions = computed(() => (
  schedulerStore.toolOptions.map((tool) => ({
    label: tool.description ? `${tool.name} - ${tool.description}` : tool.name,
    value: tool.id,
  }))
))

const rules = computed<FormRules>(() => ({
  schedule_expr: [{ required: true, message: t('scheduler.validateCron'), trigger: 'blur' }],
  task_content: [{ required: true, message: t('scheduler.validateTask'), trigger: 'blur' }],
  tool_id: [
    {
      validator: () => formData.value.target_kind !== 'tool_call' || Boolean(formData.value.tool_id),
      message: t('scheduler.validateTool'),
      trigger: 'change',
    },
  ],
  command: [
    {
      validator: () => formData.value.target_kind !== 'script_run' || Boolean(formData.value.command.trim()),
      message: t('scheduler.validateCommand'),
      trigger: 'blur',
    },
  ],
}))

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

  const payload = {
    message: formData.value.task_content.trim(),
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
