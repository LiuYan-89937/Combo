<template>
  <n-modal v-model:show="show" preset="card" :title="modalTitle" style="width: 600px">
    <n-form ref="formRef" :model="formData" :rules="rules">
      <n-form-item :label="t('common.name')" path="display_name">
        <n-input v-model:value="formData.display_name" :placeholder="t('extensions.serverName')" />
      </n-form-item>

      <n-form-item :label="t('common.description')">
        <n-input
          v-model:value="formData.description"
          type="textarea"
          :rows="2"
          :placeholder="t('extensions.serverDescriptionPlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('extensions.command')" path="command">
        <n-input v-model:value="formData.command" placeholder="node" />
      </n-form-item>

      <n-form-item :label="t('extensions.arguments')">
        <n-input v-model:value="formData.args" placeholder="server.js" />
      </n-form-item>

      <n-form-item :label="t('extensions.cwd')">
        <n-input v-model:value="formData.cwd" placeholder="/path/to/server" />
      </n-form-item>

      <n-form-item :label="t('extensions.env')">
        <n-input
          v-model:value="formData.env"
          type="textarea"
          :rows="3"
          placeholder="KEY=value"
        />
      </n-form-item>

      <n-form-item :label="t('extensions.timeoutSeconds')">
        <n-input-number v-model:value="formData.timeout_seconds" :min="1" :max="300" />
      </n-form-item>

      <n-form-item :label="t('scheduler.enabled')">
        <n-switch v-model:value="formData.enabled" />
      </n-form-item>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" @click="handleSubmit">{{ submitText }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { NModal, NForm, NFormItem, NInput, NInputNumber, NSpace, NButton, NSwitch } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { McpServerConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  show: boolean
  item?: ExtensionItemView | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: McpServerConfig]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

interface McpFormData {
  display_name: string
  description: string
  command: string
  args: string
  cwd: string
  env: string
  timeout_seconds: number
  enabled: boolean
}

const formRef = ref<FormInst | null>(null)
const { t } = useI18n()
const modalTitle = computed(() => (props.item ? t('extensions.mcpEditTitle') : t('extensions.mcpAddTitle')))
const submitText = computed(() => (props.item ? t('common.save') : t('common.add')))
const formData = ref<McpFormData>(emptyForm())

const rules = computed<FormRules>(() => ({
  display_name: [{ required: true, message: t('extensions.validateName'), trigger: 'blur' }],
  command: [{ required: true, message: t('extensions.validateCommand'), trigger: 'blur' }],
}))

function emptyForm(): McpFormData {
  return {
    display_name: '',
    description: '',
    command: '',
    args: '',
    cwd: '',
    env: '',
    timeout_seconds: 60,
    enabled: true,
  }
}

function loadForm(item: ExtensionItemView | null | undefined): void {
  if (!item) {
    formData.value = emptyForm()
    return
  }
  const payload = item.payload || {}
  const args = Array.isArray(payload.args) ? payload.args.join(' ') : String(payload.args || '')
  formData.value = {
    display_name: String(payload.display_name || item.name || ''),
    description: String(payload.description || ''),
    command: String(payload.command || ''),
    args,
    cwd: String(payload.cwd || ''),
    env: '',
    timeout_seconds: Number(payload.timeout_seconds || 60),
    enabled: item.enabled !== false,
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) loadForm(props.item)
  }
)

watch(
  () => props.item,
  (item) => {
    if (props.show) loadForm(item)
  }
)

function handleSubmit() {
  formRef.value?.validate((errors) => {
    if (errors) return
    const server: McpServerConfig = {
      server_id: props.item?.payload?.server_id,
      display_name: formData.value.display_name.trim(),
      description: formData.value.description.trim(),
      transport: 'stdio',
      command: formData.value.command.trim(),
      args: formData.value.args.trim(),
      cwd: formData.value.cwd.trim(),
      timeout_seconds: formData.value.timeout_seconds,
      enabled: formData.value.enabled,
      source: {
        type: 'local',
        name: formData.value.display_name.trim(),
        description: formData.value.description.trim(),
      },
    }
    const env = formData.value.env.trim()
    if (env) {
      server.env = env
    }
    emit('submit', server)
  })
}
</script>
