<template>
  <n-modal v-model:show="show" preset="card" :title="t('scheduler.createTitle')" style="width: min(680px, calc(100vw - 32px))">
    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="top">
      <n-form-item :label="t('scheduler.workspace')" path="workspace_id">
        <n-select
          v-model:value="formData.workspace_id"
          :options="workspaceOptions"
          :loading="loadingWorkspaces"
          :placeholder="t('scheduler.workspacePlaceholder')"
        />
      </n-form-item>

      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi :label="t('scheduler.strategy')">
          <n-select v-model:value="formData.strategy" :options="strategyOptions" />
        </n-form-item-gi>
        <n-form-item-gi :label="t('scheduler.unattendedApproval')">
          <n-select v-model:value="formData.approval_policy" :options="approvalOptions" />
        </n-form-item-gi>
      </n-grid>

      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi :label="t('scheduler.cron')" path="schedule_expr">
          <n-input v-model:value="formData.schedule_expr" placeholder="0 9 * * *" />
        </n-form-item-gi>
        <n-form-item-gi :label="t('scheduler.enabled')">
          <n-switch v-model:value="formData.enabled" />
        </n-form-item-gi>
      </n-grid>

      <n-form-item :label="t('scheduler.task')" path="task_content">
        <n-input v-model:value="formData.task_content" type="textarea" :rows="4" :placeholder="t('scheduler.taskPlaceholder')" />
      </n-form-item>

      <n-alert v-if="!loadingWorkspaces && workspaceOptions.length === 0" type="warning" :show-icon="false">
        {{ t('scheduler.workspaceRequiredHint') }}
      </n-alert>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :disabled="workspaceOptions.length === 0" @click="handleSubmit">{{ t('scheduler.create') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NFormItemGi, NGrid, NInput, NModal, NSelect, NSpace, NSwitch } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { workspaceApi, type WorkspaceProjectView } from '@/api/workspace'
import type { SchedulerJobInput } from '@/api/resourceTypes'
import type { ApprovalMode, ExecutionPreference } from '@/api/dynamicRuntime'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: SchedulerJobInput]
}>()
const { t } = useI18n()
const formRef = ref<FormInst | null>(null)
const workspaces = ref<WorkspaceProjectView[]>([])
const loadingWorkspaces = ref(false)
const formData = ref(emptyForm())
const show = computed({ get: () => props.show, set: value => emit('update:show', value) })
const workspaceOptions = computed(() => workspaces.value.map(workspace => ({
  label: `${workspace.title} — ${workspace.workdir_root}`,
  value: workspace.workspace_id,
})))
const strategyOptions = computed(() => [
  { label: t('scheduler.strategyAuto'), value: 'auto' },
  { label: t('scheduler.strategyFast'), value: 'react' },
  { label: t('scheduler.strategyPlan'), value: 'plan_and_execute' },
])
const approvalOptions = computed(() => [
  { label: t('chat.approvalAuto'), value: 'auto' },
  { label: t('chat.approvalAsk'), value: 'ask' },
  { label: t('chat.approvalAlways'), value: 'always_approval' },
])
const rules = computed<FormRules>(() => ({
  workspace_id: [requiredTextRule(t('scheduler.validateWorkspace'))],
  schedule_expr: [requiredTextRule(t('scheduler.validateCron'))],
  task_content: [requiredTextRule(t('scheduler.validateTask'))],
}))

function emptyForm() {
  return {
    workspace_id: '',
    task_content: '',
    strategy: 'auto' as ExecutionPreference,
    approval_policy: 'ask' as ApprovalMode,
    schedule_expr: '0 9 * * *',
    enabled: true,
  }
}

async function loadWorkspaces(): Promise<void> {
  loadingWorkspaces.value = true
  try {
    workspaces.value = (await workspaceApi.projects()).workspaces
    if (!formData.value.workspace_id && workspaces.value.length === 1) {
      formData.value.workspace_id = workspaces.value[0].workspace_id
    }
  } finally {
    loadingWorkspaces.value = false
  }
}

function handleSubmit(): void {
  void formRef.value?.validate((errors) => {
    if (errors) return
    emit('submit', {
      ...formData.value,
      schedule_type: 'cron',
      target: { target_type: 'graph_run', payload: { message: formData.value.task_content.trim() } },
    })
    formData.value = emptyForm()
  })
}

watch(() => props.show, (visible) => {
  if (visible) void loadWorkspaces()
}, { immediate: true })
</script>
